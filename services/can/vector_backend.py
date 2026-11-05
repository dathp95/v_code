from __future__ import annotations

from collections.abc import Mapping
from importlib import import_module
import logging
import time
from threading import get_ident
from numbers import Integral
from collections import deque
from math import isfinite
from uuid import uuid4

from services.can.can_config import CANConfig
from services.can.can_connection import CANConnectionError, CANIoError
from core.can_interface_view import CanFrameView
from services.can.owned_vector_bus import new_owned_vector_bus
from services.can.can_device import (
    CANChannelInfo, CANDeviceInfo, CANDependencyError, CANDiscoveryError,
    CANNoChannelsError, VectorDriverUnavailableError,
)

LOG = logging.getLogger(__name__)

# XL_HardwareType.XL_HWTYPE_VIRTUAL: the "Virtual Channel" device the Vector driver always reports,
# even with no adapter attached. It is not a USB-CAN interface, so it is never offered for connection.
XL_HWTYPE_VIRTUAL = 1


class VectorBackend:

    def __init__(self, *, can_module=None, vector_module=None):
        self._bus = None
        self._can_module = can_module
        self._vector_module = vector_module
        self._cleanup_failed = False
        self._owner_thread_id = None
        self._time_origin = time.monotonic()
        self._channel = None

    def fn_open(self, config: CANConfig):
        if self._bus is not None:
            raise CANConnectionError("Disconnect cleanly before opening another CAN connection.")
        if self._cleanup_failed:
            raise CANConnectionError("CAN resource cleanup is uncertain. Restart V-CODE.", recovery_required=True)

        try:
            can = self._can_module or import_module("can")
        except ImportError as error:
            raise CANConnectionError(
                "python-can is not installed. Please install python-can before connecting Vector hardware."
            ) from error

        candidate = None
        try:
            if config.channel_index is not None:
                self._revalidate_target(config)
            metadata = {}
            if config.serial is not None:
                metadata["serial"] = config.serial
            if config.channel_index is not None:
                metadata["channel_index"] = config.channel_index
            arguments = dict(
                channel=config.channel,
                bitrate=config.bitrate,
                app_name="",
                **metadata,
            )
            if self._can_module is not None:
                # Injectable factory for hardware-free tests / existing callers.
                candidate = can.Bus(interface=config.interface, **arguments)
            else:
                try:
                    vector = self._vector_module or import_module("can.interfaces.vector.canlib")
                except (ImportError, OSError) as error:
                    raise CANConnectionError("Vector XL Driver is unavailable.") from error
                if vector.xldriver is None:
                    raise CANConnectionError("Vector XL Driver is unavailable.")
                candidate = new_owned_vector_bus(vector)
                candidate.__init__(**arguments)
            self._bus = candidate
            self._owner_thread_id = get_ident()
            self._channel = config.channel
            self._time_origin = time.monotonic()
            self._wall_origin = time.time()
            self._last_wall = self._wall_origin
            self._session_id = uuid4().hex
            self._sequence = 0
            self._accepted_tx = deque(maxlen=256)
        except Exception as error:
            LOG.exception("Vector connection initialization failed")
            if candidate is not None:
                try:
                    candidate.shutdown()
                except Exception:
                    LOG.exception("Partial Vector connection cleanup failed")
                    self._bus = candidate
                    self._cleanup_failed = True
            if self._cleanup_failed:
                raise CANConnectionError("Cannot confirm cleanup after Vector initialization failure. Restart V-CODE.", recovery_required=True) from error
            if isinstance(error, CANConnectionError):
                raise
            # A foreign factory may allocate resources before raising, without
            # exposing an object to close. Never declare that case clean.
            uncertain = candidate is None and self._can_module is not None
            self._cleanup_failed = uncertain
            raise CANConnectionError(
                self._translate_error(error), recovery_required=uncertain,
                rediscovery_required=getattr(error, "error_code", None) in (120, 129)
            ) from error

    def _revalidate_target(self, config):
        try:
            vector = self._vector_module or import_module("can.interfaces.vector.canlib")
            snapshot, can_mask = self._query_driver_config(vector)
        except Exception as error:
            raise CANConnectionError("Vector XL Driver is unavailable.") from error
        matches = [snapshot.channel[i] for i in range(snapshot.channelCount)
                   if snapshot.channel[i].channelIndex == config.channel_index]
        if len(matches) != 1:
            raise CANConnectionError("Selected Vector channel is unavailable. Refresh devices.", rediscovery_required=True)
        channel = matches[0]
        fields = ((config.serial, channel.serialNumber), (config.hw_type, channel.hwType),
                  (config.hw_index, channel.hwIndex), (config.hw_channel, channel.hwChannel))
        if (not channel.channelBusCapabilities & can_mask
                or config.channel != channel.hwChannel
                or any(expected is not None and expected != actual for expected, actual in fields)):
            raise CANConnectionError("Selected Vector hardware/channel changed. Refresh devices; no alternate channel was opened.", rediscovery_required=True)

    def fn_close(self):
        if self._owner_thread_id is not None and self._owner_thread_id != get_ident():
            raise CANConnectionError('Vector bus must be closed on its owner thread.')
        if self._cleanup_failed:
            raise CANConnectionError("CAN resource cleanup is uncertain. Restart V-CODE.", recovery_required=True)
        bus = self._bus
        if bus is None:
            return

        try:
            shutdown = getattr(bus, "shutdown", None)
            if callable(shutdown):
                shutdown()
                self._bus = None
                self._owner_thread_id = None
                return

            close = getattr(bus, "close", None)
            if callable(close):
                close()
                self._bus = None
                self._owner_thread_id = None
                return
            raise RuntimeError("CAN bus has no cleanup method")
        except Exception as error:
            LOG.exception("Vector CAN cleanup failed")
            self._cleanup_failed = True
            raise CANConnectionError(
                "Cannot release Vector CAN resource. Restart V-CODE before reconnecting.", recovery_required=True
            ) from error

    def fn_is_connected(self):
        return self._bus is not None

    @property
    def capture_session_id(self):
        return self._session_id if self._bus is not None else ''

    def _guard_io(self):
        if self._bus is None or self._cleanup_failed or self._owner_thread_id != get_ident():
            raise CANConnectionError('Vector I/O requires a connected bus on its owner thread.')

    def fn_send_frame(self, can_id, data):
        self._guard_io()
        can = self._can_module or import_module('can')
        try:
            message = can.Message(arbitration_id=can_id, data=data, is_extended_id=False, check=True)
            self._bus.send(message, timeout=0.0)
        except Exception as error:
            LOG.exception('Vector send failed')
            raise CANIoError('Vector CAN send failed. Disconnect/rediscovery is required.') from error
        frame=self._raw_frame('TX',can_id,len(data),bytes(data),origin='driver_accepted')
        self._accepted_tx.append(frame)
        return frame

    def fn_receive_frame(self, timeout=0.0):
        self._guard_io()
        try:
            message=self._bus.recv(timeout=timeout)
        except Exception as error:
            LOG.exception('Vector receive failed')
            raise CANIoError('Vector CAN receive failed. Disconnect/rediscovery is required.') from error
        if message is None:
            return None
        if message.channel is not None and message.channel != self._channel:
            raise ValueError('Vector RX channel does not match the selected local CAN port; capture mapping is uncertain.')
        if message.is_fd:
            LOG.warning('Ignoring unsupported CAN FD frame on Classical CAN session')
            return None
        rx=message.is_rx
        raw_data = bytes(message.data) if message.data is not None else b''
        raw_dlc = message.dlc if isinstance(message.dlc, int) and not isinstance(message.dlc, bool) else len(raw_data)
        if raw_dlc > 8:
            dlc = 8
            data = raw_data[:8]
        else:
            dlc = raw_dlc
            data = raw_data
        return self._raw_frame('RX' if rx else 'TX',message.arbitration_id,dlc,data,
            stamp=message.timestamp,source_channel=message.channel,extended=message.is_extended_id,
            origin='' if rx else 'observed_echo',remote=message.is_remote_frame,error=message.is_error_frame)

    def _raw_frame(self,direction,can_id,dlc,data,*,stamp=None,source_channel=None,
                   extended=False,origin='',remote=False,error=False):
        now=time.monotonic()
        fallback=self._wall_origin+(now-self._time_origin)
        usable=isinstance(stamp,(int,float)) and not isinstance(stamp,bool) and isfinite(stamp) and abs(stamp-fallback)<86400
        wall=stamp if usable else fallback
        policy='driver' if usable else 'anchored_tx' if direction=='TX' and origin=='driver_accepted' else 'fallback'
        # Acquisition order is authoritative, including accepted TX before FC.
        # Retain the original driver stamp and expose every adjustment explicitly.
        if wall<self._last_wall:
            wall=self._last_wall
            policy+='_clamped'
        self._last_wall=wall
        self._sequence+=1
        echo_of=None
        if origin=='observed_echo':
            for accepted in tuple(self._accepted_tx):
                age=now-accepted.monotonic_timestamp_s
                if age>1.0:
                    self._accepted_tx.remove(accepted)
                elif (accepted.can_id,accepted.data,accepted.is_extended_id)==(can_id,data,extended):
                    echo_of=accepted.sequence
                    self._accepted_tx.remove(accepted)
                    break
        return CanFrameView(max(0,wall-self._wall_origin),direction,can_id,dlc,data,wall,now,
            self._channel,extended,origin,remote,error,self._session_id,self._sequence,
            source_channel,stamp if isinstance(stamp,(int,float)) and isfinite(stamp) else None,policy,echo_of)

    @property
    def recovery_required(self):
        return self._cleanup_failed

    def fn_refresh(self) -> tuple[CANDeviceInfo, ...]:
        if self.fn_is_connected() or self._cleanup_failed:
            raise CANDiscoveryError("Disconnect the active CAN session before refreshing Vector devices.")
        try:
            can = self._can_module or import_module("can")
        except ImportError as error:
            raise CANDependencyError("python-can is not installed.") from error
        try:
            vector = self._vector_module or import_module("can.interfaces.vector.canlib")
        except (ImportError, OSError) as error:
            raise VectorDriverUnavailableError("Vector XL Driver is unavailable.") from error
        if vector.xldriver is None:
            raise VectorDriverUnavailableError("Vector XL Driver is unavailable.")

        # python-can 4.6.1 get_channel_configs() suppresses VectorError. A strict
        # driver query distinguishes a driver failure from a valid empty result.
        # Reuse its existing XL bindings, never xlOpenPort or can.Bus here.
        # Source: https://python-can.readthedocs.io/en/stable/_modules/can/interfaces/vector/canlib.html
        snapshot, can_mask = self._query_driver_config(vector)
        total = snapshot.channelCount
        can_count = sum(bool(snapshot.channel[i].channelBusCapabilities & can_mask) for i in range(total))
        if not total:
            return ()
        if not can_count:
            raise CANNoChannelsError("The detected Vector device has no available CAN channel.")
        try:
            # None is forwarded to concurrent.futures.wait in installed 4.6.1:
            # keep ownership until detection stops, rather than orphaning timed-out calls.
            records = can.detect_available_configs(interfaces=["vector"], timeout=None)
            if not records:
                raise CANDiscoveryError("Vector discovery returned no configuration for reported CAN hardware. Refresh again.")
            return self._normalize_devices(records, can_mask)
        except CANDiscoveryError:
            raise
        except Exception as error:
            LOG.exception("Unexpected Vector discovery failure")
            raise CANDiscoveryError("Vector device discovery failed. Check the application log.") from error

    def _query_driver_config(self, vector):
        driver = vector.xldriver
        if driver is None:
            raise VectorDriverUnavailableError("Vector XL Driver is unavailable.")
        try:
            driver.xlOpenDriver()
            try:
                snapshot = vector.xlclass.XLdriverConfig()
                driver.xlGetDriverConfig(snapshot)
                can_mask = int(vector.xldefine.XL_BusCapabilities.XL_BUS_ACTIVE_CAP_CAN)
            finally:
                try:
                    driver.xlCloseDriver()
                except Exception:
                    self._cleanup_failed = True
                    raise
        except Exception as error:
            LOG.exception("Vector driver configuration query failed")
            raise VectorDriverUnavailableError("Vector XL Driver is unavailable.") from error
        return snapshot, can_mask

    @staticmethod
    def _normalize_devices(records, can_mask):
        groups = {}
        global_indices = set()
        skipped_virtual = False
        for ordinal, record in enumerate(records):
            if not isinstance(record, Mapping):
                raise CANDiscoveryError("Invalid Vector discovery metadata.")
            if record.get("interface", "vector") != "vector":
                continue
            native = record.get("vector_channel_config")
            capabilities = getattr(native, "channel_bus_capabilities", None)
            if capabilities is not None and not int(capabilities) & can_mask:
                continue

            def number(key, attribute=None):
                value = record.get(key)
                if value is None and native is not None:
                    value = getattr(native, attribute or key, None)
                if value is None:
                    return None
                if isinstance(value, bool) or not isinstance(value, Integral) or value < 0:
                    raise CANDiscoveryError(f"Invalid Vector {key} metadata.")
                return int(value)

            serial = number("serial", "serial_number")
            hw_type, hw_index = number("hw_type"), number("hw_index")
            if hw_type == XL_HWTYPE_VIRTUAL:
                skipped_virtual = True
                continue
            hw_channel, channel_index = number("hw_channel"), number("channel_index")
            channel = number("channel")
            if channel is None:
                channel = hw_channel if hw_channel is not None else channel_index
            if channel is None:
                raise CANDiscoveryError("Vector discovery did not identify a CAN channel.")
            if channel_index is not None:
                if channel_index in global_indices:
                    raise CANDiscoveryError("Ambiguous duplicate Vector global channel index.")
                global_indices.add(channel_index)
            name = record.get("name") or getattr(native, "name", None)
            name = name.strip() if isinstance(name, str) and name.strip() else "Vector Device"
            if hw_type is not None and hw_index is not None:
                key = ("hardware", serial, hw_type, hw_index)
            else:
                key = ("isolated", channel_index if channel_index is not None else ordinal)
            fd = record.get("supports_fd", False)
            if fd is not None and not isinstance(fd, (bool, Integral)):
                raise CANDiscoveryError("Invalid Vector CAN FD capability metadata.")
            label = f"CAN {hw_channel + 1}" if hw_channel is not None else f"CAN {channel + 1}"
            info = CANChannelInfo(channel, channel_index, label, bool(fd), hw_channel)
            if key not in groups:
                groups[key] = (name, serial, hw_type, hw_index, [])
            groups[key][4].append(info)
        if not groups:
            if skipped_virtual:
                return ()  # Only the driver's virtual device exists: same as no adapter attached.
            raise CANNoChannelsError("The detected Vector device has no available CAN channel.")
        return tuple(CANDeviceInfo(name, serial, hw_type, hw_index, tuple(channels), repr(key))
                     for key, (name, serial, hw_type, hw_index, channels) in groups.items())

    @staticmethod
    def _translate_error(error: Exception):
        code = getattr(error, "error_code", None)
        if code in (120, 129):
            return "Selected Vector hardware is unavailable. Refresh devices before connecting."
        if code in (111, 112, 147, 204):
            return "Selected Vector CAN channel is unavailable or invalid."
        if code in (116, 158):
            return "Selected Vector channel is busy or initialization access is unavailable."
        if code == 201:
            return "Vector XL Driver is unavailable."
        message = str(error).strip() or error.__class__.__name__
        lower_message = message.lower()

        if "xl driver library" in lower_message or "xl_driver" in lower_message:
            return "XL Driver Library is unavailable. Please check Vector driver installation."

        if "driver" in lower_message and "not" in lower_message:
            return "Vector driver is missing or unavailable."

        if "channel" in lower_message and "invalid" in lower_message:
            return "Invalid Vector CAN channel. Please select another channel."

        if "hardware" in lower_message or "device" in lower_message:
            return "Vector hardware is not connected or not detected."

        if "in use" in lower_message or "already" in lower_message:
            return "Selected Vector CAN channel is already in use."

        if "bitrate" in lower_message or "baud" in lower_message:
            return "Cannot configure the requested CAN bitrate."

        return "Cannot initialize Vector CAN. Check the application log."

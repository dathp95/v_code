import sys
import types
import unittest
from unittest.mock import Mock, patch

from services.can import CANConfig
from services.can.can_device import CANDependencyError, CANDiscoveryError, CANNoChannelsError, VectorDriverUnavailableError
from services.can.vector_backend import VectorBackend


def record(serial=123456, global_index=5, hw_channel=0, hw_index=0, name="VN1630A", **overrides):
    data = dict(interface="vector", channel=hw_channel, serial=serial,
                channel_index=global_index, hw_type=57, hw_index=hw_index,
                hw_channel=hw_channel, supports_fd=True,
                vector_channel_config=types.SimpleNamespace(name=name, channel_bus_capabilities=65536))
    data.update(overrides)
    return data


class VectorDiscoveryTests(unittest.TestCase):
    def backend(self, records=(), total=0, can_count=0):
        driver = Mock()
        channels = [types.SimpleNamespace(channelBusCapabilities=65536 if i < can_count else 0)
                    for i in range(total)]
        vector = types.SimpleNamespace(
            xldriver=driver,
            xlclass=types.SimpleNamespace(XLdriverConfig=lambda: types.SimpleNamespace(channelCount=total, channel=channels)),
            xldefine=types.SimpleNamespace(XL_BusCapabilities=types.SimpleNamespace(XL_BUS_ACTIVE_CAP_CAN=65536)),
        )
        can = types.SimpleNamespace(detect_available_configs=Mock(return_value=list(records)), Bus=Mock())
        return VectorBackend(can_module=can, vector_module=vector), can, vector

    def test_no_hardware_is_empty_and_never_opens_bus(self):
        backend, can, vector = self.backend()
        self.assertEqual(backend.fn_refresh(), ())
        can.Bus.assert_not_called()
        vector.xldriver.xlCloseDriver.assert_called_once()
        vector.xldriver.xlOpenPort.assert_not_called()
        vector.xldriver.xlActivateChannel.assert_not_called()
        vector.xldriver.xlCanTransmit.assert_not_called()

    def test_vector_virtual_channels_alone_mean_no_hardware(self):
        # Vector driver always reports "Virtual Channel" (XL_HWTYPE_VIRTUAL = 1) even with no adapter plugged in.
        virtual = [record(serial=0, hw_type=1, name="Virtual Channel", global_index=i, hw_channel=i) for i in (0, 1)]
        backend, can, _ = self.backend(virtual, total=2, can_count=2)
        self.assertEqual(backend.fn_refresh(), ())
        can.Bus.assert_not_called()

    def test_vector_virtual_channels_are_dropped_next_to_real_hardware(self):
        records = [record(serial=0, hw_type=1, name="Virtual Channel", global_index=0, hw_channel=0),
                   record(global_index=5), record(global_index=8, hw_channel=1)]
        backend, _, _ = self.backend(records, total=3, can_count=3)
        devices = backend.fn_refresh()
        self.assertEqual([device.name for device in devices], ["VN1630A"])
        self.assertEqual([c.channel_index for c in devices[0].channels], [5, 8])

    def test_channels_preserve_native_global_serial_and_driver_name(self):
        backend, can, _ = self.backend([record(), record(global_index=8, hw_channel=1)], total=2, can_count=2)
        devices = backend.fn_refresh()
        self.assertEqual(len(devices), 1)
        device = devices[0]
        self.assertEqual((device.name, device.serial), ("VN1630A", 123456))
        self.assertEqual([(c.channel, c.channel_index, c.hw_channel) for c in device.channels], [(0, 5, 0), (1, 8, 1)])
        self.assertTrue(device.channels[0].supports_fd)
        can.detect_available_configs.assert_called_once_with(interfaces=["vector"], timeout=None)
        can.Bus.assert_not_called()

    def test_installed_public_detection_api_accepts_owned_unbounded_wait(self):
        import can

        _, _, vector = self.backend(total=1, can_count=1)
        callback = Mock(return_value=[record()])
        backend = VectorBackend(can_module=can, vector_module=vector)
        with patch("can.interface._get_class_for_interface", return_value=types.SimpleNamespace(
            _detect_available_configs=callback
        )), patch.object(can, "Bus") as bus:
            devices = backend.fn_refresh()
        callback.assert_called_once()
        self.assertEqual(devices[0].channels[0].channel_index, 5)
        bus.assert_not_called()

    def test_one_channel_missing_optional_fields_is_conservatively_connectable(self):
        backend, can, _ = self.backend([dict(interface="vector", channel=0, channel_index=12)], total=1, can_count=1)
        device = backend.fn_refresh()[0]
        self.assertEqual(device.name, "Vector Device")
        self.assertIsNone(device.serial)
        self.assertTrue(device.channels[0].can_connect)
        self.assertFalse(device.channels[0].supports_fd)
        can.Bus.assert_not_called()

    def test_missing_global_index_disables_connection_without_losing_device(self):
        backend, _, _ = self.backend([record(channel_index=None)], total=1, can_count=1)
        channel = backend.fn_refresh()[0].channels[0]
        self.assertIsNone(channel.channel_index)
        self.assertFalse(channel.can_connect)

    def test_ambiguous_global_index_is_rejected(self):
        backend, _, _ = self.backend([record(), record(hw_index=1)], total=2, can_count=2)
        with self.assertRaisesRegex(CANDiscoveryError, "duplicate"):
            backend.fn_refresh()

    def test_same_model_and_duplicate_serial_use_hardware_identity(self):
        backend, _, _ = self.backend([record(), record(global_index=10, hw_index=1)], total=2, can_count=2)
        devices = backend.fn_refresh()
        self.assertEqual(len(devices), 2)
        self.assertNotEqual(devices[0].identity, devices[1].identity)

    def test_missing_identity_is_not_merged_or_given_invented_model(self):
        records = [record(serial=None, hw_type=None, hw_index=None, vector_channel_config=None),
                   record(serial=None, global_index=9, hw_type=None, hw_index=None, vector_channel_config=None)]
        backend, _, _ = self.backend(records, total=2, can_count=2)
        devices = backend.fn_refresh()
        self.assertEqual(len(devices), 2)
        self.assertTrue(all(d.name == "Vector Device" for d in devices))
        self.assertNotEqual(devices[0].identity, devices[1].identity)

    def test_device_without_can_channels_is_not_no_hardware(self):
        backend, _, _ = self.backend(total=2, can_count=0)
        with self.assertRaisesRegex(CANNoChannelsError, "no available CAN channel"):
            backend.fn_refresh()

    def test_lin_metadata_is_not_exposed_as_can(self):
        lin = record(global_index=6, vector_channel_config=types.SimpleNamespace(name="LIN", channel_bus_capabilities=0))
        backend, _, _ = self.backend([record(), lin], total=2, can_count=1)
        self.assertEqual(len(backend.fn_refresh()[0].channels), 1)

    def test_missing_dependency_and_driver_have_distinct_errors(self):
        with patch.dict(sys.modules, {"can": None}):
            with self.assertRaisesRegex(CANDependencyError, "python-can is not installed"):
                VectorBackend().fn_refresh()
        backend, _, vector = self.backend()
        vector.xldriver = None
        with self.assertRaisesRegex(VectorDriverUnavailableError, "Vector XL Driver is unavailable"):
            backend.fn_refresh()

    def test_driver_query_failure_closes_driver_and_preserves_error_cause(self):
        backend, _, vector = self.backend()
        vector.xldriver.xlGetDriverConfig.side_effect = OSError("driver failed")
        with self.assertLogs("services.can.vector_backend", level="ERROR"), self.assertRaises(VectorDriverUnavailableError) as context:
            backend.fn_refresh()
        self.assertIsInstance(context.exception.__cause__, OSError)
        vector.xldriver.xlCloseDriver.assert_called_once()

    def test_driver_open_failure_does_not_close_an_unopened_driver(self):
        backend, can, vector = self.backend()
        vector.xldriver.xlOpenDriver.side_effect = OSError("driver unavailable")
        with self.assertLogs("services.can.vector_backend", level="ERROR"), self.assertRaises(VectorDriverUnavailableError):
            backend.fn_refresh()
        vector.xldriver.xlCloseDriver.assert_not_called()
        can.Bus.assert_not_called()

    def test_vector_module_load_failure_is_not_no_hardware(self):
        backend, can, _ = self.backend()
        backend = VectorBackend(can_module=can)
        with patch("services.can.vector_backend.import_module", side_effect=FileNotFoundError("vxlapi64.dll")):
            with self.assertRaises(VectorDriverUnavailableError):
                backend.fn_refresh()

    def test_unexpected_detection_error_is_not_swallowed(self):
        backend, can, _ = self.backend(total=1, can_count=1)
        can.detect_available_configs.side_effect = RuntimeError("unexpected SDK failure")
        with self.assertLogs("services.can.vector_backend", level="ERROR"), self.assertRaises(CANDiscoveryError) as context:
            backend.fn_refresh()
        self.assertIsInstance(context.exception.__cause__, RuntimeError)

    def test_suppressed_or_empty_detection_with_can_hardware_is_an_error(self):
        backend, _, _ = self.backend(total=1, can_count=1)
        with self.assertRaises(CANDiscoveryError):
            backend.fn_refresh()

    def test_refresh_does_not_close_active_session(self):
        backend, can, _ = self.backend([record()], total=1, can_count=1)
        bus = Mock()
        backend._bus = bus
        with self.assertRaises(CANDiscoveryError):
            backend.fn_refresh()
        self.assertIs(backend._bus, bus)
        bus.shutdown.assert_not_called()
        can.Bus.assert_not_called()

    def test_connect_forwards_optional_metadata_and_legacy_config_still_works(self):
        backend, can, _ = self.backend()
        snapshot = types.SimpleNamespace(channelCount=1, channel=[types.SimpleNamespace(
            channelIndex=8, serialNumber=123456, hwType=57, hwIndex=0, hwChannel=1, channelBusCapabilities=65536)])
        with patch.object(backend, "_query_driver_config", return_value=(snapshot, 65536)):
            backend.fn_open(CANConfig("vector", 1, 500000, serial=123456, channel_index=8))
        can.Bus.assert_called_once_with(interface="vector", channel=1, bitrate=500000, app_name="", serial=123456, channel_index=8)
        backend.fn_close()
        can.Bus.reset_mock()
        backend.fn_open(CANConfig("vector", 0, 500000))
        can.Bus.assert_called_once_with(interface="vector", channel=0, bitrate=500000, app_name="")

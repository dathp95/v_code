"""Qt adapter for one composite row, using the existing owner and key job."""
from PySide6.QtCore import QObject

from core.diagnostic_request import DiagnosticOutcome as Outcome
from gui.workers.security_key_job import SecurityKeyJob
from services.can.security_access_session import SecurityAccessState


class AutoSecurityController(QObject):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.flow = self.last_flow = self._job = None

    @property
    def busy(self):
        return self.flow is not None or self._job is not None

    def start(self, request):
        owner = self.owner
        owner._invalidate_security()
        try:
            flow = owner.service.begin_auto_security(request)
        except (ValueError, RuntimeError) as error:
            owner.panel.show_notice(str(error))
            owner.panel.set_auto_step_result(request.step_id, '', 'Error', str(error))
            return
        self.flow = flow
        owner.panel.table.selectRow(owner.panel.step_ids.index(request.step_id))
        try:
            owner.security_session.start(flow.seed_request, owner._connection_identity(), owner._session_epoch)
            owner._seed_request = flow.seed_request
            self._progress('Preflight complete; requesting seed')
            self._dispatch(flow.seed_request)
        except (ValueError, RuntimeError):
            self._finish(Outcome.ERROR, detail=f'Auto {flow.level_name} could not start; no automatic retry.')

    def _progress(self, text):
        owner, flow = self.owner, self.flow
        owner.panel.set_request_busy(True)
        owner.panel.set_auto_step_result(flow.logical_request.step_id, '', 'Running', f'Auto {flow.level_name}: ' + text)
        owner.panel.show_notice(f'Auto {flow.level_name}: ' + text)

    def _current(self):
        owner, flow = self.owner, self.flow
        if flow.expired or owner._closed or not owner._seed_context_current(flow.seed_request):
            raise ValueError(f'Auto {flow.level_name} context changed.')
        owner._validate_seed_target(flow.seed_request)
        owner.service.auto_provider(flow)  # Re-check exact provider/gate, bench and owner epoch.

    def _dispatch(self, request):
        # Set identity before dispatch; even a synchronous/reentrant result is safe.
        self.owner._active = request
        if not self.owner.task.submit_diagnostic(request):
            raise ValueError('Auto security owner submission rejected.')

    def consume_result(self, result):
        flow, owner = self.flow, self.owner
        if flow is None:
            return False
        if result.request is not owner._active:
            return True  # A duplicate/stale callback cannot advance the new phase.
        owner._active = None
        try:
            self._current()
            if result.request is flow.seed_request:
                advance = flow.accept_seed(result)
                owner.security_session.receive(result, owner._connection_identity(), owner._session_epoch)
                if not advance:
                    self._finish()
                elif owner.security_session.state != SecurityAccessState.SEED_RECEIVED:
                    self._finish(Outcome.ERROR, detail='Seed validation failed.')
                else:
                    provider, gate = owner.service.auto_provider(flow)
                    flow.calculating()
                    self._progress('Calculating key')
                    job = SecurityKeyJob(owner.security_session, provider, gate, flow.seed_request)
                    job.workflow_id = flow.workflow_id
                    self._job = job
                    job.finished.connect(self._calculated)
                    job.start()
            elif result.request is flow.key_request:
                accepted = owner.security_session.finish_submission(result)
                flow.accept_key(result, accepted=accepted)
                self._finish()
        except (ValueError, RuntimeError):
            outcome = Outcome.TIMEOUT if flow.expired else Outcome.CANCELLED
            self._finish(outcome, detail=f'Auto {flow.level_name} context changed or expired; no further request sent.')
        return True

    def _calculated(self):
        job = self.sender()
        if job is not self._job:
            return
        self._job = None
        flow, owner = self.flow, self.owner
        if flow is None or job.workflow_id != flow.workflow_id:
            if not owner._closed:
                owner.panel.set_request_busy(False)
                owner._state()
            return
        try:
            self._current()
            if not job.succeeded:
                self._finish(Outcome.ERROR, detail='Verified key calculation failed or timed out; no key sent.')
                return
            self._progress('Sending key; waiting for ECU')
            key = owner.service.prepare_auto_submission(flow, owner.security_session, owner._session_epoch)
            flow.key_ready(key)
            self._dispatch(key)
        except (ValueError, RuntimeError):
            outcome = Outcome.TIMEOUT if flow.expired else Outcome.ERROR
            self._finish(outcome, detail=f'Auto {flow.level_name} authorization or provider expired; no key sent.')

    def check_timeout(self):
        if self.flow is not None and self.flow.expired:
            self.owner.task.cancel_diagnostic()
            self._finish(Outcome.TIMEOUT, detail=f'Auto {self.flow.level_name} total workflow budget expired; no retry.')

    def cancel(self):
        if self.flow is not None:
            self.owner.task.cancel_diagnostic()
            self._finish(Outcome.CANCELLED, detail=f'Auto {self.flow.level_name} cancelled; no further request sent.')

    def _finish(self, outcome=None, *, detail=''):
        flow, owner = self.flow, self.owner
        if flow is None:
            return
        if outcome is not None:
            flow.finish(outcome, detail=detail)
        if flow.result is None:
            flow.finish(Outcome.ERROR, detail=f'Auto {flow.level_name} did not complete.')
        result = flow.result
        import logging
        logging.getLogger('vcode.autosec').info('AUTO %s finished | outcome=%s | resp=%s | detail=%s',
            flow.level_name, result.outcome.value, result.response.hex(' ').upper(), result.detail)
        if result.outcome != Outcome.PASSED:
            owner.task.cancel_diagnostic()
        if result.outcome != Outcome.PASSED and owner.security_session.state != SecurityAccessState.UNLOCKED:
            owner.security_session.invalidate()
        owner.service.end_auto_security(flow)
        flow.key_request = None  # Retain only redacted metadata after completion.
        self.last_flow, self.flow = flow, None
        owner._active = owner._seed_request = None
        if not owner._closed:
            request = flow.logical_request
            if request.generation == owner.generation and owner.panel.step_for_id(request.step_id) is not None:
                detail = (result.detail + f'; UDS transactions: {len(flow.trace)}; '
                          f'UDS time: {sum(record.elapsed_s for record in flow.trace):.3f} s')
                owner.panel.set_auto_step_result(request.step_id, result.response.hex(' ').upper(),
                                                 result.outcome.value, detail)
                owner.panel.show_notice(f'Auto {flow.level_name}: ' + detail)
                owner.panel.show_notice('Simulator Auto L1: ' + detail)
            else:
                owner.panel.invalidate_step_result(request.step_id)
            owner.panel.set_request_busy(self._job is not None)
            owner._state()
            if getattr(owner, "_sequence_running", False):
                owner._on_step_finished(request.step_id)

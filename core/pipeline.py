from pathlib import Path

from core.log_parsers.diagnostics import ParserDiagnostics
from core.asc_reader import (
    load_log,
    extract_negative_responses,
    reassemble_isotp,
    extract_positive_responses,
    extract_requests,
)

from core.build_transactions import (
    build_transactions_v4,
)

from core.ecu_mapping import (
    load_vehicle_mapping,
)

from core.uds_lookup import (
    get_display_name,
    get_positive_response_timeout,
)

from core.report_engine import (
    build_ecu_reports,
    build_summary_report,
)


def refresh_display_names(result):
    """Re-apply the current display-name mapping to an analysed result, without parsing the log again.

    Names never change what was analysed (requests, responses, status, timing), so the transactions are
    only relabelled and the per-ECU reports and the summary are rebuilt from them for the export.
    """
    transactions = result["transactions"]

    for transaction in transactions:
        transaction["display_name"] = get_display_name(
            (transaction.get("request") or {}).get("payload")
        )

    result["ecu_reports"] = build_ecu_reports(transactions)
    result["summary"] = build_summary_report(result["ecu_reports"])

    return result


def run_pipeline(
        asc_file: str,
        vehicle,
        logger=None,
        progress_callback=None,
        channel=None,
    ):

    # ==========================================
    # Load Files
    if logger:
        if channel is None:
            logger("Reading log...")
        else:
            logger(f"Reading Channel {channel}...")

    parser_diagnostics = None
    if Path(asc_file).suffix.lower() == ".txt":
        parser_diagnostics = ParserDiagnostics()
        messages = load_log(asc_file, channel=channel, diagnostics=parser_diagnostics)
        parser_diagnostics.pipeline_frames = len(messages)
    else:
        messages = load_log(asc_file, channel=channel)

    if logger:
        logger("Loading vehicle configuration...")

    ecu_info, req_map, resp_map = load_vehicle_mapping(vehicle)

    if not ecu_info:
        raise ValueError(
            "Selected vehicle does not have any ECU with request and response IDs."
        )

    # ==========================================
    # Parse UDS
    if logger:
        logger("Parsing ISO-TP / UDS...")

    completed_payloads = reassemble_isotp(messages)
    requests = extract_requests(messages, completed_payloads)
    negative_responses = extract_negative_responses(messages)
    positive_responses = extract_positive_responses(completed_payloads)

    # ==========================================
    # Build Transactions
    if logger:
        logger("Building Transactions...")

    transactions = build_transactions_v4(
        requests,
        positive_responses,
        negative_responses,
        ecu_info,
        timeout=get_positive_response_timeout()
    )

    # ==========================================
    # Debug
    if logger:
        logger(f"Transactions : {len(transactions)}")

    # ==========================================
    # Report
    if logger:
        logger("Generating analysis result...")

    ecu_reports = build_ecu_reports(transactions)
    summary = build_summary_report(ecu_reports)

    if logger:
        logger("Completed with parser warnings" if parser_diagnostics and parser_diagnostics.has_warnings else "Completed")

    result = {
        "summary": summary,
        "ecu_reports": ecu_reports,
        "transactions": transactions
    }
    if parser_diagnostics is not None:
        result["parser_diagnostics"] = parser_diagnostics
    return result

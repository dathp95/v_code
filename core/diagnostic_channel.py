"""Find the diagnostic channel of a multi-channel log from the vehicle's ECU request/response CAN IDs."""
from core.ecu_mapping import load_vehicle_mapping


def diagnostic_frame_counts(channel_id_counts, vehicle):
    """{channel: number of frames whose CAN ID is a request or response ID of one of the vehicle's ECUs}.

    channel_id_counts is {channel: {can_id: frames}} as returned by get_log_channel_id_counts().
    Returns {} when there is nothing to compare (no counts, or a vehicle without usable ECU IDs).
    """
    if not channel_id_counts or vehicle is None:
        return {}
    try:
        _info, request_ids, response_ids = load_vehicle_mapping(vehicle)
    except (AttributeError, TypeError):
        return {}
    diagnostic_ids = set(request_ids) | set(response_ids)
    if not diagnostic_ids:
        return {}
    return {channel: sum(frames for can_id, frames in ids.items() if can_id in diagnostic_ids)
            for channel, ids in channel_id_counts.items()}


def detect_diagnostic_channel(channel_id_counts, vehicle):
    """The channel carrying the vehicle's diagnostic traffic, or None when it is absent or ambiguous.

    The busiest channel is usually body traffic, so channels are compared by diagnostic frames only. Two
    channels with the same top count are not guessed between; the user picks one.
    """
    scores = diagnostic_frame_counts(channel_id_counts, vehicle)
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    if not ranked or ranked[0][1] == 0:
        return None
    if len(ranked) > 1 and ranked[1][1] == ranked[0][1]:
        return None
    return ranked[0][0]

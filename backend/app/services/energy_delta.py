def safe_energy_delta(previous_kwh, current_kwh, max_reasonable_delta_kwh=100.0):
    """
    Shelly energy_kwh is a lifetime counter.
    The first reading after a deployment can be 17,000+ kWh, so it must not be
    treated as interval consumption.

    Rules:
    - Missing values => 0
    - Counter reset / negative delta => 0
    - Unrealistic interval jump => 0
    - Normal positive delta => delta
    """
    if previous_kwh is None or current_kwh is None:
        return 0.0

    try:
        previous = float(previous_kwh)
        current = float(current_kwh)
    except (TypeError, ValueError):
        return 0.0

    delta = current - previous

    if delta <= 0:
        return 0.0

    if delta > max_reasonable_delta_kwh:
        return 0.0

    return delta

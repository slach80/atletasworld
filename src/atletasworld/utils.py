"""
Shared utilities for the atletasworld project package.

Contains formatting helpers used by the public homepage and programs views
when rendering session time strings and event/tryout date labels.
"""
import datetime


def fmt_times(start_times_str):
    """Convert a space-separated 24-hour time string to a human-readable list.

    Transforms internal storage format into display format shown on the homepage
    and owner portal.

    Args:
        start_times_str: Space-separated times like '09:00 10:30 16:30'.

    Returns:
        str: Formatted string like '9:00 AM, 10:30 AM, 4:30 PM', or '' if empty.

    Example:
        >>> fmt_times('09:00 16:30')
        '9:00 AM, 4:30 PM'
    """
    if not start_times_str:
        return ''
    results = []
    for t in start_times_str.split():
        try:
            h, m = map(int, t.split(':'))
            period = 'AM' if h < 12 else 'PM'
            h12 = h % 12 or 12
            results.append(f"{h12}:{m:02d} {period}")
        except Exception:
            results.append(t)  # fall back to raw string if parse fails
    return ', '.join(results)


def tryout_label(d):
    """Format a date object as a human-readable tryout day label.

    Args:
        d: A datetime.date object.

    Returns:
        str: Label like 'Thursday, May 21'.
    """
    return d.strftime('%A, %B %-d')


# Keep legacy underscore-prefixed aliases so existing call-sites don't break
_fmt_times = fmt_times
_tryout_label = tryout_label

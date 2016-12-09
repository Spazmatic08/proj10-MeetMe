"""
Automated nose test suite for calculating free times from busy ones
"""
import arrow

from flask_main import break_day

# Day ranges
DAY_EARLY = [{'start': '2000-01-01T04:00:00-0000',
              'end': '2000-01-01T10:00:00-0000'}]

DAY_LATE = [{'start': '2000-01-01T15:00:00-0000',
             'end': '2000-01-01T19:00:00-0000'}]

DAY_WHOLE = [{'start': '2000-01-01T02:00:00-0000',
              'end': '2000-01-01T22:00:00-0000'}]

# Constant lists for testing specific scenarios
FREE = []

BUSY_SMALL = [{'start': '2000-01-01T10:00:00-0000',
               'end': '2000-01-01T12:00:00-0000'}]

BUSY_LARGE = [{'start': '2000-01-01T06:00:00-0000',
               'end': '2000-01-01T18:00:00-0000'}]

BUSY_FREQUENT = [{'start': '2000-01-01T06:00:00-0000',
                  'end': '2000-01-01T08:00:00-0000'},
                 {'start': '2000-01-01T09:00:00-0000',
                  'end': '2000-01-01T11:00:00-0000'},
                 {'start': '2000-01-01T12:00:00-0000',
                  'end': '2000-01-01T14:00:00-0000'},
                 {'start': '2000-01-01T16:00:00-0000',
                  'end': '2000-01-01T18:00:00-0000'},
                 {'start': '2000-01-01T20:00:00-0000',
                  'end': '2000-01-01T22:00:00-0000'}]

##def test_earlyfree():
##    result = break_day(DAY_EARLY, FREE)
##    print("Result of DAY_EARLY and FREE: {}".format(result))
##    assert result == DAY_EARLY
##
##def test_latefree():
##    result = break_day(DAY_LATE, FREE)
##    print("Result of DAY_LATE and FREE: {}".format(result))
##    assert result == DAY_LATE
##
##def test_wholefree():
##    result = break_day(DAY_WHOLE, FREE)
##    print("Result of DAY_WHOLE and FREE: {}".format(result))
##    assert result == DAY_WHOLE
##
##def test_earlysmall():
##    result = break_day(DAY_EARLY, BUSY_SMALL)
##    print("Result of DAY_EARLY and BUSY_SMALL: {}".format(result))
##    assert result == DAY_EARLY
##
##def test_latesmall():
##    result = break_day(DAY_LATE, BUSY_SMALL)
##    print("Result of DAY_LATE and BUSY_SMALL: {}".format(result))
##    assert result == DAY_LATE
##
##def test_wholesmall():
##    result = break_day(DAY_WHOLE, BUSY_SMALL)
##    print("Result of DAY_WHOLE and BUSY_SMALL: {}".format(result))
##    assert result == [{'start': '2000-01-01T02:00:00-0000',
##                       'end': '2000-01-01T10:00:00-0000'},
##                      {'start': '2000-01-01T12:00:00-0000',
##                       'end': '2000-01-01T22:00:00-0000'}]

def test_earlylarge():
    result = break_day(DAY_EARLY, BUSY_LARGE)
    print("Result of DAY_EARLY and BUSY_LARGE: {}".format(result))
    assert result == [{'start': '2000-01-01T04:00:00-0000',
                       'end': '2000-01-01T06:00:00-0000'}]

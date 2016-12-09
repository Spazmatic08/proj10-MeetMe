import flask
from flask import render_template
from flask import request
from flask import url_for
import uuid
import copy

import json
import logging

# Date handling 
import arrow # Replacement for datetime, based on moment.js
# import datetime # But we still need time
from dateutil import tz  # For interpreting local times


# OAuth2  - Google library implementation for convenience
from oauth2client import client
import httplib2   # used in oauth2 flow

# Google API for services 
from apiclient import discovery

# Mongo database
from pymongo import MongoClient
import secrets.admin_secrets
import secrets.client_secrets
MONGO_CLIENT_URL = "mongodb://{}:{}@localhost:{}/{}".format(
    secrets.client_secrets.db_user,
    secrets.client_secrets.db_user_pw,
    secrets.admin_secrets.port, 
    secrets.client_secrets.db)

####
# Database connection per server process
###

try: 
    dbclient = MongoClient(MONGO_CLIENT_URL)
    db = getattr(dbclient, secrets.client_secrets.db)
    collection = db.schedule

except:
    print("Failure opening database.  Is Mongo running? Correct password?")
    sys.exit(1)

###
# Globals
###
import CONFIG
import secrets.admin_secrets  # Per-machine secrets
import secrets.client_secrets # Per-application secrets

app = flask.Flask(__name__)
app.debug=CONFIG.DEBUG
app.logger.setLevel(logging.DEBUG)
app.secret_key=CONFIG.secret_key

SCOPES = 'https://www.googleapis.com/auth/calendar'
CLIENT_SECRET_FILE = secrets.admin_secrets.google_key_file
APPLICATION_NAME = 'MeetMe class project'

#############################
#
#  Pages (routed from URLs)
#
#############################

@app.route("/")
@app.route("/index")
@app.route("/choose")
def choose():
    ## We'll need authorization to list calendars 
    ## I wanted to put what follows into a function, but had
    ## to pull it back here because the redirect has to be a
    ## 'return'
    app.logger.debug("Entering index")
    if 'begin_date' not in flask.session:
      init_session_values()
    app.logger.debug("Checking credentials for Google calendar access")
    credentials = valid_credentials()
    if not credentials:
      app.logger.debug("Redirecting to authorization")
      return flask.redirect(flask.url_for('oauth2callback'))

    gcal_service = get_gcal_service(credentials)
    app.logger.debug("Returned from get_gcal_service")
    flask.g.calendars = list_calendars(gcal_service)
    if 'cal_ids' in flask.session:
      set_freebusy(gcal_service)
    return render_template('index.html')

@app.route("/create_event")
def create_event():
    ## Bring the user to the event creation page
    app.logger.debug("Entering event creation")
    flask.session['target_date'] = request.args.get('date')
    flask.session['time_min'] = request.args.get('start')
    flask.session['time_max'] = request.args.get('end')

    app.logger.debug("Checking credentials for Google calendar access")
    credentials = valid_credentials()
    if not credentials:
      app.logger.debug("Redirecting to authorization")
      return flask.redirect(flask.url_for('oauth2callback'))

    gcal_service = get_gcal_service(credentials)
    app.logger.debug("Returned from get_gcal_service")
    flask.g.calendars = list_calendars(gcal_service)
    
    return render_template('create_event.html')

@app.route("/_invite", methods = ['POST'])
def _invite():
    ## Insert the newly created event into the database, create and
    ## display the invitation link.
    app.logger.debug("Entering invitation generation")
    entry = request.form

    date = arrow.get(entry['date'].split(' ')[1], 'MM/DD/YYYY')
    start = entry['tpBegin']
    end = entry['tpEnd']

    event_arrows = single_day(date, start, end)
    event = { 'start': { 'dateTime': event_arrows[0].isoformat() },
              'end': { 'dateTime': event_arrows[1].isoformat() },
              'description': entry['description'],
              'summary': entry['eventName'] }
    db_id = arrow.utcnow().timestamp

    db_entry = { '_id': db_id, 'event': event }

    # Acquire the GCal service
    app.logger.debug("Checking credentials for Google calendar access")
    credentials = valid_credentials()
    if not credentials:
      app.logger.debug("Redirecting to authorization")
      return flask.redirect(flask.url_for('oauth2callback'))
    
    gcal_service = get_gcal_service(credentials)

    # We need to add the event to the creator's calendar
    event = gcal_service.events().insert(
        calendarId=entry['calselect'],
        body=event).execute()

    collection.insert(db_entry)

    # Generate a link to the created event
    link_url = flask.url_for('_respond', event_id=db_id, _external=True)
    flask.session['meeting_url'] = link_url
    
    return flask.redirect(flask.url_for('choose'))

@app.route("/_respond/<event_id>")
def _respond(event_id):
    # Acquire the event details from the database
    event = collection.find_one({ '_id': int(event_id) })['event']

    # Acquire the GCal service (again)
    app.logger.debug("Checking credentials for Google calendar access")
    credentials = valid_credentials()
    if not credentials:
      app.logger.debug("Redirecting to authorization")
      return flask.redirect(flask.url_for('oauth2callback'))

    gcal_service = get_gcal_service(credentials)

    # Set things we will need up
    flask.g.calendars = list_calendars(gcal_service)
    flask.g.event = event
    flask.session['event_id'] = event_id
    
    return flask.render_template('respond.html')


@app.route("/rsvp", methods=["POST"])
def rsvp():
    if request.form['choice'] == 'Decline':
        return flask.redirect(url_for('choose'))
    
    calselect = request.form['calselect']
    app.logger.debug("Snsjvdklnjsklnvjskdlfhjvklsfdnjvklsndjkfl")
    app.logger.debug("{}".format(calselect))
    
    # Acquire the GCal service (again)
    app.logger.debug("Checking credentials for Google calendar access")
    credentials = valid_credentials()
    if not credentials:
      app.logger.debug("Redirecting to authorization")
      return flask.redirect(flask.url_for('oauth2callback'))
    
    gcal_service = get_gcal_service(credentials)

    # Find the event details in the database
    event = collection.find_one({ '_id':
                                  int(flask.session['event_id']) })['event']

    # Place the event onto the user's calendar
    event = gcal_service.events().insert(
        calendarId=calselect,
        body=event).execute()

    return flask.redirect(url_for('choose'))


####
#
#  Google calendar authorization:
#      Returns us to the main /choose screen after inserting
#      the calendar_service object in the session state.  May
#      redirect to OAuth server first, and may take multiple
#      trips through the oauth2 callback function.
#
#  Protocol for use ON EACH REQUEST: 
#     First, check for valid credentials
#     If we don't have valid credentials
#         Get credentials (jump to the oauth2 protocol)
#         (redirects back to /choose, this time with credentials)
#     If we do have valid credentials
#         Get the service object
#
#  The final result of successful authorization is a 'service'
#  object.  We use a 'service' object to actually retrieve data
#  from the Google services. Service objects are NOT serializable ---
#  we can't stash one in a cookie.  Instead, on each request we
#  get a fresh serivce object from our credentials, which are
#  serializable. 
#
#  Note that after authorization we always redirect to /choose;
#  If this is unsatisfactory, we'll need a session variable to use
#  as a 'continuation' or 'return address' to use instead. 
#
####

def valid_credentials():
    """
    Returns OAuth2 credentials if we have valid
    credentials in the session.  This is a 'truthy' value.
    Return None if we don't have credentials, or if they
    have expired or are otherwise invalid.  This is a 'falsy' value. 
    """
    if 'credentials' not in flask.session:
      return None

    credentials = client.OAuth2Credentials.from_json(
        flask.session['credentials'])

    if (credentials.invalid or
        credentials.access_token_expired):
      return None
    return credentials


def get_gcal_service(credentials):
  """
  We need a Google calendar 'service' object to obtain
  list of calendars, busy times, etc.  This requires
  authorization. If authorization is already in effect,
  we'll just return with the authorization. Otherwise,
  control flow will be interrupted by authorization, and we'll
  end up redirected back to /choose *without a service object*.
  Then the second call will succeed without additional authorization.
  """
  app.logger.debug("Entering get_gcal_service")
  http_auth = credentials.authorize(httplib2.Http())
  service = discovery.build('calendar', 'v3', http=http_auth)
  app.logger.debug("Returning service")
  return service

@app.route('/oauth2callback')
def oauth2callback():
  """
  The 'flow' has this one place to call back to.  We'll enter here
  more than once as steps in the flow are completed, and need to keep
  track of how far we've gotten. The first time we'll do the first
  step, the second time we'll skip the first step and do the second,
  and so on.
  """
  app.logger.debug("Entering oauth2callback")
  flow =  client.flow_from_clientsecrets(
      CLIENT_SECRET_FILE,
      scope= SCOPES,
      redirect_uri=flask.url_for('oauth2callback', _external=True))
  ## Note we are *not* redirecting above.  We are noting *where*
  ## we will redirect to, which is this function. 
  
  ## The *second* time we enter here, it's a callback 
  ## with 'code' set in the URL parameter.  If we don't
  ## see that, it must be the first time through, so we
  ## need to do step 1. 
  app.logger.debug("Got flow")
  if 'code' not in flask.request.args:
    app.logger.debug("Code not in flask.request.args")
    auth_uri = flow.step1_get_authorize_url()
    return flask.redirect(auth_uri)
    ## This will redirect back here, but the second time through
    ## we'll have the 'code' parameter set
  else:
    ## It's the second time through ... we can tell because
    ## we got the 'code' argument in the URL.
    app.logger.debug("Code was in flask.request.args")
    auth_code = flask.request.args.get('code')
    credentials = flow.step2_exchange(auth_code)
    flask.session['credentials'] = credentials.to_json()
    ## Now I can build the service and execute the query,
    ## but for the moment I'll just log it and go back to
    ## the main screen
    app.logger.debug("Got credentials")
    return flask.redirect(flask.url_for('choose'))

#####
#
#  Option setting:  Buttons or forms that add some
#     information into session state.  Don't do the
#     computation here; use of the information might
#     depend on what other information we have.
#   Setting an option sends us back to the main display
#      page, where we may put the new information to use. 
#
#####

@app.route('/busytimes', methods=['POST'])
def busytimes():
    """
    User chose a date range, time range, and set of calendars
    using the checkboxes and widgets. 
    """
    app.logger.debug("Entering busytimes")
    daterange = request.form.get('daterange')
    begin_time = request.form.get('tpBegin')
    end_time = request.form.get('tpEnd')
    flask.session['begin_time'] = begin_time
    flask.session['end_time'] = end_time
    calselect = request.form.getlist('calselect')
    flask.session['daterange'] = daterange
    daterange_parts = daterange.split(" - ")
    flask.session['begin_date'] = interpret_date(daterange_parts[0])
    flask.session['end_date'] = interpret_date(daterange_parts[1])
    flask.session['cal_ids'] = calselect
    return flask.redirect(flask.url_for("choose"))

####
#
#   Initialize session variables 
#
####

def init_session_values():
    """
    Start with some reasonable defaults for date and time ranges.
    Note this must be run in app context ... can't call from main. 
    """
    # Default date span = tomorrow to 1 week from now, 8 to 5
    now = arrow.now('local')     # We really should be using tz from browser
    tomorrow = now.replace(days=+1, hours=8)
    nextweek = now.replace(days=+7, hours=17)
    flask.session["begin_date"] = tomorrow.floor('day').isoformat()
    flask.session["end_date"] = nextweek.ceil('day').isoformat()
    flask.session["daterange"] = "{} - {}".format(
        tomorrow.format("MM/DD/YYYY h:mm A"),
        nextweek.format("MM/DD/YYYY h:mm A"))
    # Default time span each day, 8 to 5
    flask.session["begin_time"] = "8:00"
    flask.session["end_time"] = "17:00"

def interpret_time( text ):
    """
    Read time in a human-compatible format and
    interpret as ISO format with local timezone.
    May throw exception if time can't be interpreted. In that
    case it will also flash a message explaining accepted formats.
    """
    app.logger.debug("Decoding time '{}'".format(text))
    time_formats = ["ha", "h:mma",  "h:mm a", "H:mm"]
    try: 
        as_arrow = arrow.get(text, time_formats).replace(tzinfo=tz.tzlocal())
        as_arrow = as_arrow.replace(year=2016) #HACK see below
        app.logger.debug("Succeeded interpreting time")
    except:
        app.logger.debug("Failed to interpret time")
        flask.flash("Time '{}' didn't match accepted formats 13:30 or 1:30pm"
              .format(text))
        raise
    return as_arrow.isoformat()
    #HACK #Workaround
    # isoformat() on raspberry Pi does not work for some dates
    # far from now.  It will fail with an overflow from time stamp out
    # of range while checking for daylight savings time.  Workaround is
    # to force the date-time combination into the year 2016, which seems to
    # get the timestamp into a reasonable range. This workaround should be
    # removed when Arrow or Dateutil.tz is fixed.
    # FIXME: Remove the workaround when arrow is fixed (but only after testing
    # on raspberry Pi --- failure is likely due to 32-bit integers on that platform)


def interpret_date( text ):
    """
    Convert text of date to ISO format used internally,
    with the local time zone.
    """
    try:
      as_arrow = arrow.get(text, "MM/DD/YYYY").replace(
          tzinfo=tz.tzlocal())
    except:
        flask.flash("Date '{}' didn't fit expected format 12/31/2001")
        raise
    return as_arrow.isoformat()

def next_day(isotext):
    """
    ISO date + 1 day (used in query to Google calendar)
    """
    as_arrow = arrow.get(isotext)
    return as_arrow.replace(days=+1).isoformat()

####
#
#  Functions (NOT pages) that return some information
#
####

def set_freebusy(service):
    """
    Given a google 'service' object, sets the session variable 'busy' to
    reflect when the queried individual is busy.
    """
    app.logger.debug("Entering list_busy")
    day_ranges = daily_ranges()
    ids = [{"id": cal_id} for cal_id in flask.session['cal_ids']]
    busy = [ ]
    avbl = [ ]
    for times in day_ranges:
      # Acquire the busy times from Google Calendars using the passed service
      open_time = times[0].isoformat()
      close_time = times[1].isoformat()
      fbquery = { "timeMin": open_time,
                  "timeMax": close_time,
                  "timeZone": "-0800", # Replace with browswer tz
                  "items": ids } 
      response = service.freebusy().query(body=fbquery).execute()

      # Collect the returned busy times for each day
      busy_that_day = [ ]
      for b in response['calendars'].values():
        busy_that_day.extend(b['busy'])
      busy.extend(busy_that_day)
      dearrowed_times = [{'start': times[0].format("YYYY-MM-DDTHH:mm:ssZ"), 
                         'end': times[1].format("YYYY-MM-DDTHH:mm:ssZ")}]
      avbl.extend(break_day(dearrowed_times, busy_that_day))

    flask.session['busy'] = busy
    flask.session['avbl'] = avbl

def break_day(dayrange, interrupts):
    """
    Breaks up a pair of start-end times into a list of start-end times
    with the interrupt times removed from the range's time span. End result
    is a list of 2 arrow lists containing the windows of time that are
    available.
    """
    result = copy.deepcopy(dayrange)
    for i in interrupts:
        scrutiny = result[-1]

        # Need arrows for good time deltas
        i_start = arrow.get(i['start'], "YYYY-MM-DDTHH:mm:ssZ")
        i_end = arrow.get(i['end'], "YYYY-MM-DDTHH:mm:ssZ")
        s_start = arrow.get(scrutiny['start'], "YYYY-MM-DDTHH:mm:ssZ")
        s_end = arrow.get(scrutiny['end'], "YYYY-MM-DDTHH:mm:ssZ")

        # Arrows can be compared via inequalities - if one arrow is
        # greater than another, then it starts later.
        if (i_start <= s_start and i_end >= s_end):
            # Interrupt is larger than interval itself
            del result[-1]
        elif (i_start <= s_start and i_end < s_end and i_end > s_start):
            # Interrupt starts before the interval, but ends in middle
            result[-1]['start'] = i['end']
        elif (i_start > s_start and i_start < s_end and i_end >= s_end):
            # Interrupt starts within interval, and carries through the rest
            result[-1]['end'] = i['start']
        elif (i_start > s_start and i_end < s_end):
            # Interrupt splits interval in two
            new_parts = [{'start': scrutiny['start'],
                          'end': i['start']},
                         {'start': i['end'],
                          'end': scrutiny['end']}]
            del result[-1]
            result.extend(new_parts)
        
    return result

def daily_ranges():
    """
    Returns a sequence of date and time ranges as a list of tuples
    based on the contents of the session variables for use in determining
    busy times.
    """
    app.logger.debug("Entering daily_ranges")
    begin_date = arrow.get(flask.session['begin_date'])
    end_date = arrow.get(flask.session['end_date'])
    begin_time = flask.session['begin_time']
    end_time = flask.session['end_time']
    result = [ ]
    for date in arrow.Arrow.range('day', begin_date, end_date):
      result.append(single_day(date, begin_time, end_time))
    return result

def single_day(date, begin_time, end_time):
    """
    Acquires a pair of arrows from the timepickers representing a single
    start and end time
    """
    begin_offset = [int(n) for n in
                    begin_time.split(":")]
    end_offset = [int(n) for n in
                  end_time.split(":")]

    day = arrow.get(date)

    day_start = day.replace(hours=+begin_offset[0],
                            minutes=+begin_offset[1],
                            tzinfo=tz.tzlocal())
    day_end = day.replace(hours=+end_offset[0],
                          minutes=+end_offset[1],
                          tzinfo=tz.tzlocal())
    return [day_start, day_end]

def list_calendars(service):
    """
    Given a google 'service' object, return a list of
    calendars.  Each calendar is represented by a dict.
    The returned list is sorted to have
    the primary calendar first, and selected (that is, displayed in
    Google Calendars web app) calendars before unselected calendars.
    """
    app.logger.debug("Entering list_calendars")  
    calendar_list = service.calendarList().list().execute()["items"]
    result = [ ]
    for cal in calendar_list:
        kind = cal["kind"]
        id = cal["id"]
        if "description" in cal: 
            desc = cal["description"]
        else:
            desc = "(no description)"
        summary = cal["summary"]
        # Optional binary attributes with False as default
        selected = ("selected" in cal) and cal["selected"]
        primary = ("primary" in cal) and cal["primary"]
        

        result.append(
          { "kind": kind,
            "id": id,
            "summary": summary,
            "selected": selected,
            "primary": primary
            })
    return sorted(result, key=cal_sort_key)


def cal_sort_key( cal ):
    """
    Sort key for the list of calendars:  primary calendar first,
    then other selected calendars, then unselected calendars.
    (" " sorts before "X", and tuples are compared piecewise)
    """
    if cal["selected"]:
       selected_key = " "
    else:
       selected_key = "X"
    if cal["primary"]:
       primary_key = " "
    else:
       primary_key = "X"
    return (primary_key, selected_key, cal["summary"])


#################
#
# Functions used within the templates
#
#################

@app.template_filter( 'fmtdate' )
def format_arrow_date( date ):
    try: 
        normal = arrow.get( date )
        return normal.format("ddd MM/DD/YYYY")
    except:
        return "(bad date)"

@app.template_filter( 'fmttime' )
def format_arrow_time( time ):
    try:
        normal = arrow.get( time ).to('local')
        return normal.format("hh:mm A")
    except:
        return "(bad time)"
    
#############


if __name__ == "__main__":
  # App is created above so that it will
  # exist whether this is 'main' or not
  # (e.g., if we are running under green unicorn)
  app.run(port=CONFIG.PORT,host="0.0.0.0")
    

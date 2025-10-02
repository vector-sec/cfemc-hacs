"""API for CF-EMC Energy."""

import requests
from bs4 import BeautifulSoup
from datetime import datetime
import json
import logging

from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

class CFEMCApi:
    """The class for handling the data retrieval."""

    def __init__(self, username, password, member_number, account_number):
        self.username = username
        self.password = password
        self.member_number = member_number
        self.account_number = account_number
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36'})
        self.login_url = "https://billing.utility.org/onlineportal/Customer-Login"
        self.usage_url = "https://billing.utility.org/onlineportal/My-Account/Usage-History"
        self.daily_url = "https://billing.utility.org/onlineportal/DesktopModules/MeterUsage/API/MeterData.aspx/GetDailyUsageData"
        self.hourly_url = "https://billing.utility.org/onlineportal/DesktopModules/MeterUsage/API/MeterData.aspx/GetIntervalData"
        self._is_logged_in = False # Add a flag to track login status

    def _login(self):
        """Log in to the utility's website."""
        _LOGGER.debug("Attempting to login.")
        get_response = self.session.get(self.login_url)
        get_response.raise_for_status()
        soup = BeautifulSoup(get_response.text, 'html.parser')
        
        viewstate = soup.find('input', {'name': '__VIEWSTATE'})
        eventvalidation = soup.find('input', {'name': '__EVENTVALIDATION'})
        requestverificationtoken = soup.find('input', {'name': '__RequestVerificationToken'})

        if not all([viewstate, eventvalidation, requestverificationtoken]):
            self._is_logged_in = False
            _LOGGER.error("Could not find all required login form fields.")
            raise ConnectionError("Login page structure may have changed.")

        viewstate_val = viewstate['value']
        eventvalidation_val = eventvalidation['value']
        requestverificationtoken_val = requestverificationtoken['value']
        
        login_payload = {
            "ScriptManager": "dnn$ctr384$CustomerLogin$UpdatePanel1|dnn$ctr384$CustomerLogin$btnLogin",
            "__EVENTTARGET": "",
            "__EVENTARGUMENT": "",
            "__VIEWSTATE": viewstate_val,
            "__VIEWSTATEGENERATOR": "F57EDA00",
            "__EVENTVALIDATION": eventvalidation_val,
            "__RequestVerificationToken": requestverificationtoken_val,
            "dnn$ctr384$CustomerLogin$txtUsername": self.username,
            "dnn$ctr384$CustomerLogin$txtPassword": self.password,
            "LBD_VCID_c_default_dnn_ctr384_customerlogin_logincaptcha": "7b42de4e898b42f084aa13cb82c55df2",
            "LBD_BackWorkaround_c_default_dnn_ctr384_customerlogin_logincaptcha": "1",
            "dnn$ctr384$CustomerLogin$CaptchaCodeTextBox": "ASDF",
            "dnn$ctr384$CustomerLogin$hdnSecretkey": "",
            "dnn$ctr384$CustomerLogin$HiddenField1": "",
            "__ASYNCPOST": "true",
            "dnn$ctr384$CustomerLogin$btnLogin": "Sign In"
        }
        
        post_response = self.session.post(self.login_url, data=login_payload)
        post_response.raise_for_status()

        if self.username not in post_response.text:
            self._is_logged_in = False
            _LOGGER.error("Login failed. Response text did not contain username.")
            raise ConnectionError("Login failed. Please check credentials.")
        
        self._is_logged_in = True
        _LOGGER.debug("Login successful.")
        return True

    def _ensure_logged_in(self):
        """Check if the session is active, and log in if it's not."""
        if self._is_logged_in:
            _LOGGER.debug("Session is already active. Skipping login.")
            return

        self._login()

    def test_credentials(self):
        """Test if the provided credentials are valid."""
        try:
            return self._login()
        except Exception as e:
            _LOGGER.error(f"Credential test failed: {e}")
            return False
        finally:
            # Clear the session after testing to ensure a fresh login on the first run.
            self.session = requests.Session()
            self._is_logged_in = False

    def get_hourly_data(self, start_date, end_date):
        """Fetch hourly energy data for a date range."""
        _LOGGER.debug(f"Getting hourly data for {start_date.strftime('%Y-%m-%d')}")
        
        # This will now only login if the session is not already active.
        self._ensure_logged_in()

        start_date_str = start_date.strftime('%m/%d/%Y')
        end_date_str = end_date.strftime('%m/%d/%Y')

        daily_payload = {'keymbr': str(self.member_number),'MemberSep':f'{self.member_number}-{self.account_number}','StartDate': start_date_str,'EndDate': end_date_str,'IsEnergy':'false','IsPPM':'false','IsCostEnable':'3'}
        hourly_payload = {'keymbr': str(self.member_number),'MemberSep':f'{self.member_number}-{self.account_number}','StartDate': start_date_str,'EndDate': end_date_str,'IntervalType':'60'}
        
        self.session.headers['Content-Type'] = 'application/json; charset=UTF-8'

        try:
            _LOGGER.debug("Getting usage page session...")
            self.session.get(self.usage_url).raise_for_status()

            daily_payload_str = str(daily_payload)
            _LOGGER.debug(f"Requesting daily stats with payload: {daily_payload_str}")
            self.session.post(self.daily_url, data=daily_payload_str).raise_for_status()

            hourly_payload_str = str(hourly_payload)
            _LOGGER.debug(f"Requesting hourly stats with payload: {hourly_payload_str}")
            api_response = self.session.post(self.hourly_url, data=hourly_payload_str)
            api_response.raise_for_status()

        except requests.exceptions.RequestException as e:
            # If any request fails, the session might be invalid.
            # Reset the login flag to force a new login on the next attempt.
            _LOGGER.warning(f"A request failed: {e}. Session may be invalid. Forcing re-login on next attempt.")
            self._is_logged_in = False
            raise # Re-raise the exception to be handled by the coordinator

        hourly_response_json = json.loads(api_response.text).get('d',{}).get('Items',[{}])
        usage_data = hourly_response_json

        processed_data = []
        for entry in usage_data:
            naive_timestamp = datetime.strptime(entry['UsageHourDate'], '%m/%d/%Y %I:%M %p')
            aware_timestamp = dt_util.as_local(naive_timestamp)
            
            kwh_str = entry.get('KWH')
            if kwh_str == 'NaN' or kwh_str is None:
                usage = 0.0
            else:
                usage = float(kwh_str)

            processed_data.append({
                'time': aware_timestamp,
                'usage': usage
            })
            
        return processed_data

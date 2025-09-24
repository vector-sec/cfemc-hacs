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
            _LOGGER.error("Login failed. Response text did not contain username.")
            raise ConnectionError("Login failed. Please check credentials.")
        _LOGGER.debug("Login successful.")
        return True

    def test_credentials(self):
        """Test if the provided credentials are valid."""
        try:
            return self._login()
        except Exception as e:
            _LOGGER.error(f"Credential test failed: {e}")
            return False

    def get_hourly_data(self, start_date, end_date):
        """Fetch hourly energy data for a date range."""
        _LOGGER.debug("Starting get_hourly_data")
        self._login()

        start_date_str = start_date.strftime('%m/%d/%Y')
        end_date_str = end_date.strftime('%m/%d/%Y')

        daily_payload = {'keymbr': str(self.member_number),'MemberSep':f'{self.member_number}-{self.account_number}','StartDate': start_date_str,'EndDate': end_date_str,'IsEnergy':'false','IsPPM':'false','IsCostEnable':'3'}
        hourly_payload = {'keymbr': str(self.member_number),'MemberSep':f'{self.member_number}-{self.account_number}','StartDate': start_date_str,'EndDate': end_date_str,'IntervalType':'60'}
        
        self.session.headers['Content-Type'] = 'application/json; charset=UTF-8'

        _LOGGER.debug("Getting usage page session...")
        self.session.get(self.usage_url).raise_for_status()

        daily_payload_str = str(daily_payload)
        _LOGGER.debug(f"Requesting daily stats with payload: {daily_payload_str}")
        self.session.post(self.daily_url, data=daily_payload_str).raise_for_status()

        hourly_payload_str = str(hourly_payload)
        _LOGGER.debug(f"Requesting hourly stats with payload: {hourly_payload_str}")
        api_response = self.session.post(self.hourly_url, data=hourly_payload_str)
        api_response.raise_for_status()

        hourly_response_json = json.loads(api_response.text).get('d',{}).get('Items',[{}])
        usage_data = hourly_response_json

        processed_data = []
        for entry in usage_data:
            # The timestamp is local time from the utility.
            naive_timestamp = datetime.strptime(entry['UsageHourDate'], '%m/%d/%Y %I:%M %p')
            
            # Make the timestamp timezone-aware using Home Assistant's local timezone
            aware_timestamp = dt_util.as_local(naive_timestamp)
            
            # Handle cases where KWH is 'NaN' or missing
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


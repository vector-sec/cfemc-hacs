"""API for CF-EMC Energy."""

import json
import logging
from datetime import datetime
import requests
from bs4 import BeautifulSoup

from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30


class CFEMCApi:
    """The class for handling the data retrieval."""

    def __init__(self, username, password, member_number, account_number):
        self.username = username
        self.password = password
        self.member_number = member_number
        self.account_number = account_number
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36'
        })
        self.login_url = "https://billing.utility.org/onlineportal/Customer-Login"
        self.usage_url = "https://billing.utility.org/onlineportal/My-Account/Usage-History"
        self.daily_url = "https://billing.utility.org/onlineportal/DesktopModules/MeterUsage/API/MeterData.aspx/GetDailyUsageData"
        self.hourly_url = "https://billing.utility.org/onlineportal/DesktopModules/MeterUsage/API/MeterData.aspx/GetIntervalData"
        self._is_logged_in = False

    def _login(self):
        """Log in to the utility's website with a fresh session."""
        _LOGGER.debug("Attempting to login to CF-EMC portal.")
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36'
        })
        self._is_logged_in = False

        get_response = self.session.get(self.login_url, timeout=REQUEST_TIMEOUT)
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

        post_response = self.session.post(self.login_url, data=login_payload, timeout=REQUEST_TIMEOUT)
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
        if not self._is_logged_in:
            self._login()

    def test_credentials(self):
        """Test if the provided credentials are valid."""
        try:
            return self._login()
        except Exception as e:
            _LOGGER.error(f"Credential test failed: {e}")
            return False
        finally:
            self.session = requests.Session()
            self._is_logged_in = False

    def get_hourly_data(self, start_date, end_date):
        """Fetch hourly energy data for a date range with automatic re-authentication on session expiry."""
        start_date_str = start_date.strftime('%m/%d/%Y')
        end_date_str = end_date.strftime('%m/%d/%Y')
        _LOGGER.debug(f"Getting interval data for {start_date_str} to {end_date_str}")

        daily_payload = {
            'keymbr': str(self.member_number),
            'MemberSep': f'{self.member_number}-{self.account_number}',
            'StartDate': start_date_str,
            'EndDate': end_date_str,
            'IsEnergy': 'false',
            'IsPPM': 'false',
            'IsCostEnable': '3'
        }

        headers = {
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'Accept-Language': 'en-US,en;q=0.9',
            'Content-Type': 'application/json; charset=utf-8',
            'X-Requested-With': 'XMLHttpRequest',
            'Origin': 'https://billing.utility.org',
            'Referer': self.usage_url,
        }

        # Attempt up to 2 times to handle expired server sessions automatically
        for attempt in range(2):
            try:
                self._ensure_logged_in()

                _LOGGER.debug("Navigating to usage page session...")
                usage_res = self.session.get(self.usage_url, timeout=REQUEST_TIMEOUT)
                usage_res.raise_for_status()

                # If redirected to login page, the existing session expired
                if "Customer-Login" in usage_res.url or ("CustomerLogin" in usage_res.text and self.username not in usage_res.text):
                    _LOGGER.debug("Usage page indicated expired session. Resetting login flag.")
                    self._is_logged_in = False
                    if attempt == 0:
                        continue
                    raise ConnectionError("Session expired and re-login failed.")

                daily_payload_str = json.dumps(daily_payload)
                _LOGGER.debug(f"Priming daily stats session context with payload: {daily_payload_str}")
                self.session.post(
                    self.daily_url,
                    data=daily_payload_str,
                    headers=headers,
                    timeout=REQUEST_TIMEOUT
                )

                def safe_float(v):
                    if v is None or v == "" or str(v).strip() == "NaN":
                        return None
                    try:
                        return float(v)
                    except (ValueError, TypeError):
                        return None

                # CF-EMC meters provide 30-minute intervals for recent dates and 60-minute intervals for older history
                usage_data = []
                for interval_type in ['30', '60']:
                    interval_payload = {
                        'keymbr': str(self.member_number),
                        'MemberSep': f'{self.member_number}-{self.account_number}',
                        'StartDate': start_date_str,
                        'EndDate': end_date_str,
                        'IntervalType': interval_type
                    }
                    interval_payload_str = json.dumps(interval_payload)
                    _LOGGER.debug(f"Requesting interval stats with IntervalType={interval_type}: {interval_payload_str}")
                    api_response = self.session.post(
                        self.hourly_url,
                        data=interval_payload_str,
                        headers=headers,
                        timeout=REQUEST_TIMEOUT
                    )
                    api_response.raise_for_status()

                    resp_text = api_response.text.strip()
                    # Check for HTML login redirect response
                    if resp_text.startswith("<") or "CustomerLogin" in resp_text:
                        _LOGGER.debug("Received HTML response instead of JSON. Session expired.")
                        self._is_logged_in = False
                        if attempt == 0:
                            break
                        raise ConnectionError("Session expired while requesting hourly data.")

                    response_json = json.loads(resp_text)
                    items = response_json.get('d', {}).get('Items', [])
                    if items and any(safe_float(it.get('KWH')) is not None for it in items):
                        usage_data = items
                        _LOGGER.debug(f"Retrieved {len(items)} valid intervals using IntervalType={interval_type} for {start_date_str}")
                        break

                if not usage_data:
                    _LOGGER.debug(f"No valid interval records returned for {start_date_str}; data not yet published by CF-EMC.")
                    return []

                # Aggregate intervals into hourly buckets
                hourly_buckets = {}
                for entry in usage_data:
                    if not isinstance(entry, dict) or 'UsageHourDate' not in entry:
                        continue

                    try:
                        naive_timestamp = datetime.strptime(entry['UsageHourDate'], '%m/%d/%Y %I:%M %p')
                        aware_timestamp = dt_util.as_local(naive_timestamp)
                    except (ValueError, TypeError) as err:
                        _LOGGER.warning(f"Could not parse timestamp '{entry.get('UsageHourDate')}': {err}")
                        continue

                    kwh = safe_float(entry.get('KWH'))
                    if kwh is None:
                        kwh = 0.0

                    hour_key = aware_timestamp.replace(minute=0, second=0, microsecond=0)
                    if hour_key not in hourly_buckets:
                        hourly_buckets[hour_key] = 0.0

                    hourly_buckets[hour_key] += kwh

                processed_data = [
                    {
                        'time': hour_dt,
                        'usage': round(usage_val, 4),
                    }
                    for hour_dt, usage_val in sorted(hourly_buckets.items())
                ]

                return processed_data

            except (requests.exceptions.RequestException, json.JSONDecodeError, ConnectionError) as e:
                _LOGGER.warning(f"Request failed (attempt {attempt + 1}/2): {e}. Resetting session.")
                self._is_logged_in = False
                if attempt == 0:
                    continue
                raise

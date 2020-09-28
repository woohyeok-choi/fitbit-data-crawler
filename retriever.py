from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.remote.webdriver import WebDriver
import urllib.parse as url_parser
import base64
import requests
import time
from typing import Tuple


class FitbitDataRetriever:
    _OAUTH_AUTH_URI = "https://www.fitbit.com/oauth2/authorize"
    _OAUTH_TOKEN_ACCESS_URI = "https://api.fitbit.com/oauth2/token"

    _RESOURCE_MINUTES_SEDENTARY = 'activities/tracker/minutesSedentary'
    _RESOURCE_MINUTES_LIGHTLY_ACTIVE = 'activities/tracker/minutesLightlyActive'
    _RESOURCE_MINUTES_FAIRLY_ACTIVE = 'activities/tracker/minutesFairlyActive'
    _RESOURCE_MINUTES_VERY_ACTIVE = 'activities/tracker/minutesVeryActive'
    _RESOURCE_ACTIVITY_CALORIES = 'activities/tracker/activityCalories'

    _RESOURCE_CALORIES_INTRA = 'activities/calories'
    _RESOURCE_STEPS_INTRA = 'activities/steps'
    _RESOURCE_DISTANCE_INTRA = 'activities/distance'
    _RESOURCE_FLOORS_INTRA = 'activities/floors'
    _RESOURCE_ELEVATION_INTRA = 'activities/elevation'
    _RESOURCE_HEART_INTRA = 'activities/heart'

    _RESOURCE_SLEEP = 'sleep'

    def __init__(self, selenium_path: str, client_id: str, client_secret: str, callback: str, call_interval: int):
        self._selenium_path = selenium_path
        self._client_id = client_id
        self._client_secret = client_secret
        self._callback = callback
        self._call_interval = call_interval

    def _auth_url(self) -> str:
        return f'{self._OAUTH_AUTH_URI}?response_type=code&' \
               f'client_id={self._client_id}&' \
               f'redirect_uri={self._callback}&' \
               f'scope=activity%20heartrate%20%20profile%20sleep'

    @staticmethod
    def _handle_sign_in(browser: WebDriver, email: str, password: str):
        input_email = browser.find_element_by_css_selector('#loginForm input[type="email"]')
        input_password = browser.find_element_by_css_selector('#loginForm input[type="password"]')
        button_sign_in = browser.find_element_by_css_selector('#loginForm button')

        input_email.send_keys(email)
        input_password.send_keys(password)
        button_sign_in.submit()

    def _check_auth_code_screen(self, browser: WebDriver):
        current_url = browser.current_url
        is_redirect = current_url.startswith(self._callback)
        try:
            browser.find_element_by_css_selector("#selectAllScope")
            is_scope_selection = True
        except NoSuchElementException:
            is_scope_selection = False
        return is_redirect or is_scope_selection

    def _get_auth_code(self, browser: WebDriver) -> str:
        wait = WebDriverWait(browser, 120).until(lambda b: self._check_auth_code_screen(b))

        if wait is not True:
            raise Exception("Not found auth_code")

        current_url = browser.current_url

        if current_url.startswith(self._callback):
            result = url_parser.urlparse(current_url)
            query = url_parser.parse_qs(result.query, strict_parsing=True)
            return query['code'][-1]
        else:
            browser.find_element_by_css_selector("#selectAllScope").click()
            browser.find_element_by_css_selector('#allow-button').click()
            return self._get_auth_code(browser)

    def _get_auth_token(self, auth_code: str) -> Tuple[str, str, str]:
        id_and_secret = f'{self._client_id}:{self._client_secret}'.encode()
        auth_header = base64.encodebytes(id_and_secret).decode('utf-8').strip()

        response = requests.post(
            url=self._OAUTH_TOKEN_ACCESS_URI,
            headers={
                'Authorization': f'Basic {auth_header}',
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            data={
                'client_id': self._client_id,
                'grant_type': 'authorization_code',
                'redirect_uri': self._callback,
                'code': auth_code
            }
        )

        status_code = response.status_code
        content = response.json()

        if status_code != 200:
            raise Exception(f'Authorization failed\n {content}')
        else:
            access_token = content['access_token']
            refresh_token = content['refresh_token']
            user_id = content['user_id']
            return access_token, refresh_token, user_id

    def _refresh_auth_token(self, refresh_token: str) -> Tuple[str, str, str]:
        id_and_secret = f'{self._client_id}:{self._client_secret}'.encode()
        auth_header = base64.encodebytes(id_and_secret).decode('utf-8').strip()

        response = requests.post(
            url=self._OAUTH_TOKEN_ACCESS_URI,
            headers={
                'Authorization': f'Basic {auth_header}',
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            data={
                'grant_type': 'refresh_token',
                'refresh_token': refresh_token,
            }
        )
        status_code = response.status_code
        content = response.json()

        if status_code != 200:
            raise Exception(f'Authorization failed\n {content}')
        else:
            access_token = content['access_token']
            refresh_token = content['refresh_token']
            user_id = content['user_id']
            return access_token, refresh_token, user_id

    def _get_data(self, url: str, access_token: str, refresh_token: str, trial: int = 0):
        time.sleep(self._call_interval)

        response = requests.get(
            url=url,
            headers={
                'Authorization': f'Bearer  {access_token}'
            }
        )
        status_code = response.status_code
        content = response.json()

        if status_code == 401 and any([error['errorType'] == 'expired_token' for error in content['errors']]):
            if trial > 5:
                raise Exception(f'Failed to retrieve refresh token.')

            self._refresh_auth_token(refresh_token)
            return self._get_data(url, access_token, refresh_token, trial + 1)
        elif status_code == 200:
            return content
        else:
            raise Exception(f'Unhandled Error\n {content}')

    def _get_activity_data(self, user_id: str, date: str, resource: str, access_token: str, refresh_token: str) -> dict:
        url = f'https://api.fitbit.com/1/user/{user_id}/{resource}/date/{date}/1d.json'
        return self._get_data(url=url, access_token=access_token, refresh_token=refresh_token)

    def _get_intra_day_activity_data(self, user_id: str, date: str, resource: str, access_token: str,
                                     refresh_token: str) -> dict:
        url = f'https://api.fitbit.com/1/user/{user_id}/{resource}/date/{date}/1d/1min.json'
        return self._get_data(url=url, access_token=access_token, refresh_token=refresh_token)

    def _get_intra_day_heart_rate_data(self, user_id: str, date: str, access_token: str, refresh_token: str) -> dict:
        url = f'https://api.fitbit.com/1/user/{user_id}/{self._RESOURCE_HEART_INTRA}/date/{date}/1d/1sec.json'
        return self._get_data(url=url, access_token=access_token, refresh_token=refresh_token)

    @staticmethod
    def _get_simple_value(d: dict, key: str):
        if key in d and d[key]:
            return d[key][-1]['value']
        else:
            return '-'

    @staticmethod
    def _get_intraday_value(d: dict, key: str) -> list:
        if key in d and d[key] and 'dataset' in d[key] and d[key]['dataset']:
            return d[key]['dataset']
        else:
            return []

    def _get_all_data(self, user_id: str, date: str, access_token: str, refresh_token: str):
        result = {
            'date': date
        }

        min_sedentary = self._get_activity_data(
            user_id, date, self._RESOURCE_MINUTES_SEDENTARY, access_token, refresh_token
        )
        result['minutesSedentary'] = self._get_simple_value(min_sedentary, 'activities-tracker-minutesSedentary')

        min_lightly_active = self._get_activity_data(
            user_id, date, self._RESOURCE_MINUTES_LIGHTLY_ACTIVE, access_token, refresh_token
        )
        result['minutesLightlyActive'] = self._get_simple_value(min_lightly_active,
                                                                'activities-tracker-minutesLightlyActive')

        min_fairly_active = self._get_activity_data(
            user_id, date, self._RESOURCE_MINUTES_FAIRLY_ACTIVE, access_token, refresh_token
        )
        result['minutesFairlyActive'] = self._get_simple_value(min_fairly_active,
                                                               'activities-tracker-minutesFairlyActive')

        min_very_active = self._get_activity_data(
            user_id, date, self._RESOURCE_MINUTES_VERY_ACTIVE, access_token, refresh_token
        )
        result['minutesVeryActive'] = self._get_simple_value(min_very_active, 'activities-tracker-minutesVeryActive')

        min_activity_calories = self._get_activity_data(
            user_id, date, self._RESOURCE_ACTIVITY_CALORIES, access_token, refresh_token
        )
        result['activityCalories'] = self._get_simple_value(min_activity_calories,
                                                            'activities-tracker-activityCalories')

        intra_calories = self._get_intra_day_activity_data(
            user_id, date, self._RESOURCE_CALORIES_INTRA, access_token, refresh_token
        )
        result['calories'] = self._get_simple_value(intra_calories, 'activities-calories')
        result['calories-intraday'] = self._get_intraday_value(intra_calories, 'activities-calories-intraday')

        intra_steps = self._get_intra_day_activity_data(
            user_id, date, self._RESOURCE_STEPS_INTRA, access_token, refresh_token
        )
        result['steps'] = self._get_simple_value(intra_steps, 'activities-steps')
        result['steps-intraday'] = self._get_intraday_value(intra_steps, 'activities-steps-intraday')

        intra_distance = self._get_intra_day_activity_data(
            user_id, date, self._RESOURCE_DISTANCE_INTRA, access_token, refresh_token
        )
        result['distance'] = self._get_simple_value(intra_distance, 'activities-distance')
        result['distance-intraday'] = self._get_intraday_value(intra_distance, 'activities-distance-intraday')

        intra_floors = self._get_intra_day_activity_data(
            user_id, date, self._RESOURCE_FLOORS_INTRA, access_token, refresh_token
        )
        result['floors'] = self._get_simple_value(intra_floors, 'activities-floors')
        result['floors-intraday'] = self._get_intraday_value(intra_floors, 'activities-floors-intraday')

        intra_elevation = self._get_intra_day_activity_data(
            user_id, date, self._RESOURCE_ELEVATION_INTRA, access_token, refresh_token
        )
        result['elevation'] = self._get_simple_value(intra_elevation, 'activities-elevation')
        result['elevation-intraday'] = self._get_intraday_value(intra_elevation, 'activities-elevation-intraday')

        intra_heart_rate = self._get_intra_day_heart_rate_data(
            user_id, date, access_token, refresh_token
        )
        result['heart'] = self._get_simple_value(intra_heart_rate, 'activities-heart')
        result['heart-intraday'] = self._get_intraday_value(intra_heart_rate, 'activities-heart-intraday')

        return result

    def authorize(self, email: str, password: str) -> Tuple[str, str, str]:
        option = webdriver.ChromeOptions()
        option.add_argument("--incognito")
        option.add_argument("headless")

        with webdriver.Chrome(self._selenium_path, options=option) as browser:
            browser.implicitly_wait(10)
            browser.get(self._auth_url())

            self._handle_sign_in(
                browser=browser,
                email=email,
                password=password
            )
            print(f'-- Sign In: {email} / {password}')

            auth_code = self._get_auth_code(
                browser=browser
            )
            print(f'-- Auth code: {auth_code}')

            access_token, refresh_token, user_id = self._get_auth_token(
                auth_code=auth_code
            )
            print(f'-- Token: {access_token}')
            return access_token, refresh_token, user_id

    def retrieve(self, access_token: str, refresh_token: str, user_id: str, date: str):
        result = self._get_all_data(
            date=date,
            user_id=user_id,
            access_token=access_token,
            refresh_token=refresh_token
        )
        print(f"-- Retrieve date: {date}")

        return result


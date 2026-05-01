import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
import logging
import aiohttp
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

OPTION_SELECT_CAMPIONATO = "ליגה"
OPTION_SELECT_TEAM = "קבוצה"
OPTION_MANUAL_TEAM = "הזנה ידנית של מזהה"
OPTION_ALL_TODAY = "כל משחקי היום"

@config_entries.HANDLERS.register(DOMAIN)
class CalcioLiveConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self._errors = {}
        self._data = {}
        self._teams = []

    async def async_step_user(self, user_input=None):
        self._errors = {}

        if user_input is not None:
            selection = user_input.get("selection")

            if selection == OPTION_SELECT_CAMPIONATO:
                self._data.update(user_input)
                return await self.async_step_campionato()

            elif selection == OPTION_SELECT_TEAM:
                self._data.update(user_input)
                return await self.async_step_select_competition_for_team()
            
            elif selection == OPTION_ALL_TODAY:
                self._data.update(user_input)
                self._data["competition_code"] = "99999"  # ערך פיקטיבי ליצירת חיישן
                return self.async_create_entry(
                    title="כל משחקי היום",
                    data=self._data,
                )

            elif selection == OPTION_MANUAL_TEAM:
                self._data.update(user_input)
                return await self.async_step_manual_team()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("selection", default=OPTION_SELECT_CAMPIONATO): vol.In([OPTION_SELECT_CAMPIONATO, OPTION_SELECT_TEAM, OPTION_ALL_TODAY, OPTION_MANUAL_TEAM]),
            }),
            errors=self._errors,
            description_placeholders={
                "description": (
                    "ברוכים הבאים להגדרת Calcio Live.\n\n"
                    "בחר אחת מהאפשרויות ליצירת חיישן:\n\n"
                    "- **ליגה**: למעקב אחר כל המשחקים בליגה.\n"
                    "- **קבוצה**: למעקב אחר קבוצה ספציפית.\n"
                    "- **הכל**: למעקב אחר כל משחקי היום (בכל העולם).\n"
                    "- **הזנה ידנית**: אם אתה מכיר את מזהה הקבוצה הספציפית."
                )
            }
        )

    async def async_step_campionato(self, user_input=None):
        if user_input is not None:
            competition_code = user_input.get("competition_code")
            competition_name = await self._get_competition_name(competition_code)
            self._data.update({"competition_code": competition_code, "name": competition_name})

            return await self.async_step_dates()

        competitions = await self._get_competitions()
        sorted_competitions = {k: v for k, v in sorted(competitions.items(), key=lambda item: item[1])}

        return self.async_show_form(
            step_id="campionato",
            data_schema=vol.Schema({
                vol.Required("competition_code"): vol.In(sorted_competitions),
            }),
            errors=self._errors,
            description_placeholders={
                "description": (
                    "בחר את הליגה שברצונך לעקוב אחריה.\n"
                    "יוצגו נתונים הקשורים לכל הקבוצות בליגה שנבחרה."
                )
            }
        )

    async def async_step_select_competition_for_team(self, user_input=None):
        if user_input is not None:
            competition_code = user_input.get("competition_code")
            self._data.update({"competition_code": competition_code})

            await self._get_teams(competition_code)
            return await self.async_step_team()

        competitions = await self._get_competitions()
        sorted_competitions = {k: v for k, v in sorted(competitions.items(), key=lambda item: item[1])}

        return self.async_show_form(
            step_id="select_competition_for_team",
            data_schema=vol.Schema({
                vol.Required("competition_code"): vol.In(sorted_competitions),
            }),
            errors=self._errors,
            description_placeholders={
                "description": (
                    "בחר את הליגה שממנה תרצה לבחור קבוצה ספציפית.\n"
                    "לאחר בחירת הליגה, תוכל לבחור קבוצה מהרשימה."
                )
            }
        )

    async def async_step_team(self, user_input=None):
        if user_input is not None:
            team_name = user_input["team_name"]
            competition_code = self._data.get("competition_code", "N/A")
            competition_name = await self._get_competition_name(competition_code)

            # מציאת מזהה הקבוצה שנבחרה
            selected_team = next((team for team in self._teams if team["displayName"] == team_name), None)
            team_id = selected_team["id"] if selected_team else None

            # עדכון self._data עם team_id
            self._data.update({"team_name": team_name, "team_id": team_id, "name": f"קבוצה {competition_name} {team_name}"})

            return await self.async_step_dates()

        team_options = {team['displayName']: team['displayName'] for team in sorted(self._teams, key=lambda t: t['displayName'])}

        return self.async_show_form(
            step_id="team",
            data_schema=vol.Schema({
                vol.Required("team_name"): vol.In(team_options),
            }),
            errors=self._errors,
            description_placeholders={
                "description": (
                    "בחר את הקבוצה שברצונך לעקוב אחריה.\n"
                    "יוצגו רק המשחקים של קבוצה זו."
                )
            }
        )

    async def async_step_manual_team(self, user_input=None):
        if user_input is not None:
            team_id = user_input["manual_team_id"]
            competition_code = self._data.get("competition_code", "N/A")
            competition_name = await self._get_competition_name(competition_code)
            nome_squadra = user_input.get("name", "שם קבוצה (לבחירתך)")
            nome_squadra_normalizzato = nome_squadra.replace(" ", "_").lower()

            self._data.update({"team_id": team_id, "name": f"קבוצה {competition_name} {team_id} {nome_squadra_normalizzato}"})

            return await self.async_step_dates()

        return self.async_show_form(
            step_id="manual_team",
            data_schema=vol.Schema({
                vol.Required("manual_team_id"): str,
                vol.Optional("name", default="שם קבוצה (לבחירתך)"): str,
            }),
            errors=self._errors,
            description_placeholders={
                "description": (
                    "אם אתה מכיר את מזהה הקבוצה, תוכל להזין אותו ידנית.\n"
                    "תוכל גם לציין שם מותאם אישית לזיהוי קל יותר."
                )
            }
        )

    async def async_step_dates(self, user_input=None):
        """מסך להגדרת start_date ו-end_date."""
        today = datetime.now()

        # שליפת תאריכים דינמיים דרך _get_calendar_data
        start_date, end_date = await self._get_calendar_data()

        # אם לא נמצאו תאריכים מהלוח שנה, משתמשים בברירות מחדל
        if start_date is None or end_date is None:
            start_date = today.strftime("%Y-%m-%d")  # ברירת מחדל: תאריך היום
            end_date = (today + timedelta(days=30)).strftime("%Y-%m-%d")  # ברירת מחדל: 30 יום מהיום

        # אם המשתמש סיפק קלט, מעדכנים את הנתונים
        if user_input is not None:
            self._data.update({
                "start_date": user_input.get("start_date", start_date),
                "end_date": user_input.get("end_date", end_date),
            })
            return self.async_create_entry(
                title=self._data.get("name", "Calcio Live"),
                data=self._data,
            )

        # הצגת הטופס להזנת תאריכים עם ערכי ברירת מחדל
        return self.async_show_form(
            step_id="dates",
            data_schema=vol.Schema({
                vol.Optional("start_date", default=start_date): str,
                vol.Optional("end_date", default=end_date): str,
            }),
            description_placeholders={
                "description": (
                    "הזן את תקופת המעקב עבור המשחקים.\n\n"
                    "- תאריך ההתחלה קובע מאיזה תאריך להתחיל לעקוב.\n"
                    "- תאריך הסיום קובע עד מתי לעקוב.\n\n"
                    "שני התאריכים חייבים להיות בפורמט **YYYY-MM-DD**."
                )
            }
        )
    
    async def _get_calendar_data(self):
        """שליפת לוח המשחקים לקבלת תאריכי התחלה וסיום"""
        competition_code = self._data.get("competition_code", "N/A")

        if competition_code == "99999":
            return None, None

        calendar_url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{competition_code}/scoreboard"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(calendar_url) as response:
                    response.raise_for_status()
                    data = await response.json()
                    # חילוץ תאריכי התחלה וסיום מלוח השנה
                    calendar_start_date = data.get("calendarStartDate", "2025-08-01T04:00Z")
                    calendar_end_date = data.get("calendarEndDate", "2026-07-01T03:59Z")
                    return calendar_start_date[:10], calendar_end_date[:10]
        except Exception as e:
            _LOGGER.error(f"שגיאה בשליפת לוח המשחקים: {e}")
            return None, None
    

    async def _get_competitions(self):
        url = "https://site.api.espn.com/apis/site/v2/leagues/dropdown?lang=en&region=us&calendartype=whitelist&limit=200&sport=soccer"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    response.raise_for_status()
                    competitions_data = await response.json()
                    return {league['slug']: league['name'] for league in competitions_data.get("leagues", [])}
        except aiohttp.ClientError as e:
            _LOGGER.error(f"שגיאה בטעינת התחרויות: {e}")
            return {}

    async def _get_competition_name(self, competition_code):
        """שליפת שם התחרות לפי הקוד שלה."""
        competitions = await self._get_competitions()
        return competitions.get(competition_code, "שם לא ידוע")

    async def _get_teams(self, competition_code):
        url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{competition_code}/teams"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    response.raise_for_status()
                    teams_data = await response.json()
                
                    leagues = teams_data.get("sports", [{}])[0].get("leagues", [{}])
                    if not leagues:
                        self._teams = []
                        return

                    self._teams = [
                        {"id": team["team"]["id"], "displayName": team["team"]["displayName"]}
                        for league in leagues for team in league.get("teams", [])
                    ]
        except aiohttp.ClientError as e:
            _LOGGER.error(f"שגיאה בטעינת הקבוצות עבור {competition_code}: {e}")
            self._teams = []

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """מנהל זרימת האפשרויות."""
        return CalcioLiveOptionsFlow(config_entry)


class CalcioLiveOptionsFlow(config_entries.OptionsFlow):

    def __init__(self, config_entry):
        super().__init__()
        self._config_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        today = datetime.now()

        start_date = self._config_entry.options.get(
            "start_date", self._config_entry.data.get("start_date", (today - relativedelta(months=3)).strftime("%Y-%m-%d"))
        )
        end_date = self._config_entry.options.get(
            "end_date", self._config_entry.data.get("end_date", (today + relativedelta(months=4)).strftime("%Y-%m-%d"))
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional("start_date", default=start_date): str,
                vol.Optional("end_date", default=end_date): str,
                vol.Optional("info", default="⚠ לאחר השינוי, הפעל מחדש את Home Assistant.", description=""): str,
            }),
        )

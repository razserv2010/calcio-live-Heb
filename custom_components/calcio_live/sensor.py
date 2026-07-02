import asyncio
import aiohttp
from datetime import datetime, timedelta, timezone
from homeassistant.helpers.entity import Entity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
import random
from .const import DOMAIN, _LOGGER

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    try:
        competition_name = entry.data.get("name")
        competition_code = entry.data.get("competition_code")
        team_name = entry.data.get("team_name")
        selection = entry.data.get("selection")
        team_id = entry.data.get("team_id")
        
        start_date_1 = entry.data.get("start_date")
        end_date_1 = entry.data.get("end_date")
        
        start_date = entry.data.get("start_date", datetime.now().strftime("%Y-%m-%d"))
        end_date = entry.data.get("end_date", (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"))
        
        base_scan_interval = timedelta(minutes=entry.options.get("scan_interval", 3))
        sensors = []

        if DOMAIN not in hass.data:
            hass.data[DOMAIN] = {}
        
        _LOGGER.debug(f"Calcio Live - רשומת תצורה: {entry.data}")
    
        if team_name:
            team_name_normalized = team_name.replace(" ", "_").replace(".", "_").lower()
            competition_name = competition_code.replace(" ", "_").replace(".", "_").lower()

            sensors += [
                CalcioLiveSensor(
                    hass, f"calciolive_next_{competition_name}_{team_name_normalized}", competition_code, "team_match",
                    base_scan_interval + timedelta(seconds=random.randint(0, 30)), team_name=team_name,
                    config_entry_id=entry.entry_id, start_date=start_date, end_date=end_date, team_id=team_id
                ),
                CalcioLiveSensor(
                    hass, f"calciolive_all_{competition_name}_{team_name_normalized}", competition_code, "team_matches",
                    base_scan_interval + timedelta(seconds=random.randint(0, 30)), team_name=team_name,
                    config_entry_id=entry.entry_id, start_date=start_date, end_date=end_date, team_id=team_id
                ),
                CalcioLiveSensor(
                    hass, f"calciolive_all_mixed_{team_name_normalized}", competition_code, "team_matches_mixed",
                    base_scan_interval + timedelta(seconds=random.randint(0, 30)), team_name=team_name,
                    config_entry_id=entry.entry_id, start_date=start_date, end_date=end_date, team_id=team_id
                )
            ]
        elif competition_code:
            if competition_code == "99999":  # אם קוד התחרות הוא פיקטיבי, יוצרים חיישן לכל המשחקים
                sensors += [
                    CalcioLiveSensor(
                        hass, "calciolive_all_today", competition_code, "all_matches_today",
                        base_scan_interval + timedelta(seconds=random.randint(0, 30)), config_entry_id=entry.entry_id,
                        start_date=start_date, end_date=end_date, team_id=team_id
                    )
                ]
            else:
                competition_name = competition_name.replace(" ", "_").replace(".", "_").lower()

                sensors += [
                    CalcioLiveSensor(
                        hass, f"calciolive_classifica_{competition_name}", competition_code, "standings",
                        base_scan_interval + timedelta(seconds=random.randint(0, 30)), config_entry_id=entry.entry_id,
                        start_date=start_date, end_date=end_date, team_id=team_id
                    ),
                    CalcioLiveSensor(
                        hass, f"calciolive_all_{competition_name}", competition_code, "match_day",
                        base_scan_interval + timedelta(seconds=random.randint(0, 30)), config_entry_id=entry.entry_id,
                        start_date=start_date, end_date=end_date, team_id=team_id
                    )
                ]

        async_add_entities(sensors, True)

    except Exception as e:
        _LOGGER.error(f"שגיאה בהגדרת החיישנים: {e}")


class CalcioLiveSensor(Entity):
    _cache = {}

    def __init__(self, hass, name, code, sensor_type=None, scan_interval=timedelta(minutes=5),
                 team_name=None, config_entry_id=None, start_date=None, end_date=None, team_id=None):
        self.hass = hass
        self._name = name
        self._code = code
        self._team_id = team_id
        self._sensor_type = sensor_type
        self._scan_interval = scan_interval
        self._state = None
        self._attributes = {}
        self._config_entry_id = config_entry_id
        self._team_name = team_name
        # שימוש בתאריכים שסופקו מרשומת התצורה
        self._start_date = start_date
        self._end_date = end_date
        
        # המרת תאריכים לאובייקטי datetime
        self._start_date = datetime.strptime(self._start_date, "%Y-%m-%d")
        self._end_date = datetime.strptime(self._end_date, "%Y-%m-%d")
        
        self._request_count = 0
        self._last_request_time = None
        
        # מעקב אחר תוצאות קודמות לזיהוי שערים
        self._previous_scores = {}
        
        # מעקב אחר כרטיסים קודמים למניעת כפילויות
        self._previous_match_details = {}
        
        # מעקב אחר משחקים שהושמע להם אירוע סיום
        self._match_finished_dispatched = set()

        self.base_url = "https://site.web.api.espn.com/apis/v2/sports/soccer"
        self.base_url_2 = "https://site.api.espn.com/apis/site/v2/sports/soccer"
        self.base_url_3 = "https://site.web.api.espn.com/apis/site/v2/sports/soccer"
        
    @property
    def name(self):
        return self._name

    @property
    def state(self):
        return self._state

    @property
    def extra_state_attributes(self):
        return {
            **self._attributes,
            "request_count": self._request_count,
            "last_request_time": self._last_request_time,
            "start_date": self._start_date.strftime("%Y-%m-%d"),
            "end_date": self._end_date.strftime("%Y-%m-%d"),
        }

    @property
    def should_poll(self):
        return True

    @property
    def unique_id(self):
        return f"{self._name}_{self._sensor_type}"

    @property
    def config_entry_id(self):
        return self._config_entry_id

    async def async_update(self):
        _LOGGER.info(f"מתחיל עדכון עבור {self._name}")

        cache_key = f"{self._sensor_type}_{self._code}_{self._team_name}"
        if cache_key in CalcioLiveSensor._cache and (datetime.now() - CalcioLiveSensor._cache[cache_key]["time"]).seconds < 60:
            self._process_data(CalcioLiveSensor._cache[cache_key]["data"])
            _LOGGER.info(f"משתמש בנתונים מהמטמון עבור {self._name}")
            return

        url = await self._build_url()

        if url is None:
            return

        retries = 0
        while retries < 3:
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                    async with session.get(url) as response:
                        if response.status == 200:
                            data = await response.json()
                            _LOGGER.debug(f"נתונים התקבלו עבור {self._name}: {data}")
                            CalcioLiveSensor._cache[cache_key] = {"data": data, "time": datetime.now()}
                            self._process_data(data)
                            _LOGGER.info(f"עדכון הושלם עבור {self._name}")
                            break
                        else:
                            await asyncio.sleep(5)
                            retries += 1
            except aiohttp.ClientError as error:
                await asyncio.sleep(5)
                retries += 1
            except asyncio.TimeoutError:
                await asyncio.sleep(5)
                retries += 1

    
    async def _build_url(self):
        base_url    = "https://site.web.api.espn.com/apis/v2/sports/soccer"
        base_url_2  = "https://site.api.espn.com/apis/site/v2/sports/soccer"
        base_url_3  = "https://site.web.api.espn.com/apis/site/v2/sports/soccer"
        season_data = ""
        season_start = ""
        season_end = ""
    
        if self._code:
            season_start, season_end = await self._get_calendar_data()

        # אם התאריכים לא נשלפו, משתמשים בברירות המחדל
        if not season_start or not season_end:
            season_start = self._start_date.strftime("%Y-%m-%d")
            season_end = self._end_date.strftime("%Y-%m-%d")
    
        season_start = season_start[:10].replace("-", "")
        season_end = season_end[:10].replace("-", "")

        if self._sensor_type == "standings":
            return f"{self.base_url}/{self._code}/standings?"

        elif self._sensor_type in ("match_day", "team_match", "team_matches"):
            return f"{self.base_url_3}/{self._code}/scoreboard?limit=1000&dates={season_start}-{season_end}"

        elif self._sensor_type == "team_matches_mixed" and self._team_name:
            return f"{self.base_url_3}/all/teams/{self._team_id}/schedule?fixture=true"

        elif self._sensor_type == "all_matches_today":
            return f"{self.base_url_2}/all/scoreboard"

        return None
    
    
    async def _get_calendar_data(self):
        """שליפת לוח המשחקים לקבלת תאריכי התחלה וסיום"""
    
        if self._code == "99999":
            return None, None

        calendar_url = f"{self.base_url_2}/{self._code}/scoreboard"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(calendar_url) as response:
                    response.raise_for_status()
                    data = await response.json()
                    # חילוץ תאריכי התחלה וסיום מלוח השנה
                    calendar_start_date = data.get("calendarStartDate", "2025-08-01T04:00Z")
                    calendar_end_date = data.get("calendarEndDate", "3000-01-01T00:00Z")
                    return calendar_start_date, calendar_end_date
        except Exception as e:
            _LOGGER.error(f"שגיאה בשליפת לוח המשחקים: {e}")
            return None, None


    def _parse_match_datetime(self, date_str):
        """המרת מחרוזת תאריך מהפורמט '%d/%m/%Y %H:%M' ל-datetime עם אזור זמן המשתמש"""
        try:
            if isinstance(date_str, str):
                user_timezone = self.hass.config.time_zone
                from zoneinfo import ZoneInfo
                parsed_dt = datetime.strptime(date_str, "%d/%m/%Y %H:%M")
                local_tz = ZoneInfo(user_timezone)
                return parsed_dt.replace(tzinfo=local_tz)
            return None
        except (ValueError, TypeError):
            return None

    def _detect_and_dispatch_goals(self, matches):
        """זיהוי שערים ושידור אירועים"""
        live_matches = [m for m in matches if m.get("state") == "in"]
        
        for match in live_matches:
            match_id = f"{match.get('home_team', 'N/A')}_{match.get('away_team', 'N/A')}"
            home_score = match.get("home_score", 0)
            away_score = match.get("away_score", 0)
            
            try:
                home_score = int(home_score) if home_score != "N/A" else 0
                away_score = int(away_score) if away_score != "N/A" else 0
            except (ValueError, TypeError):
                home_score = 0
                away_score = 0
            
            # אם זו הפעם הראשונה שאנו רואים משחק זה, שמור את התוצאות
            if match_id not in self._previous_scores:
                self._previous_scores[match_id] = {
                    "home": home_score,
                    "away": away_score,
                    "match_details": match.get("match_details", []).copy()
                }
                continue
            
            prev_home = self._previous_scores[match_id]["home"]
            prev_away = self._previous_scores[match_id]["away"]
            prev_details = self._previous_scores[match_id].get("match_details", [])
            curr_details = match.get("match_details", [])
            
            # זיהוי שערים של קבוצת הבית
            if home_score > prev_home:
                goals_scored = home_score - prev_home
                goal_scorers = self._extract_goal_scorers_from_details(
                    prev_details, curr_details, goals_scored, is_home_team=True
                )
                self._dispatch_goal_event(
                    match.get("home_team", "N/A"),
                    match.get("away_team", "N/A"),
                    goals_scored,
                    home_score,
                    away_score,
                    match,
                    goal_scorers
                )
            
            # זיהוי שערים של קבוצת האורחים
            if away_score > prev_away:
                goals_scored = away_score - prev_away
                goal_scorers = self._extract_goal_scorers_from_details(
                    prev_details, curr_details, goals_scored, is_home_team=False
                )
                self._dispatch_goal_event(
                    match.get("away_team", "N/A"),
                    match.get("home_team", "N/A"),
                    goals_scored,
                    home_score,
                    away_score,
                    match,
                    goal_scorers
                )
            
            # עדכון התוצאות והפרטים
            self._previous_scores[match_id]["home"] = home_score
            self._previous_scores[match_id]["away"] = away_score
            self._previous_scores[match_id]["match_details"] = curr_details.copy()

    def _extract_goal_scorers_from_details(self, prev_details, curr_details, goals_count, is_home_team=True):
        """חילוץ שמות השחקנים שכבשו שערים מפרטי המשחק"""
        new_goals = []
        
        for detail in curr_details:
            if detail not in prev_details and "Goal" in detail:
                # פורמט: "Goal - 38': Bryan Mbeumo"
                try:
                    parts = detail.split("': ")
                    if len(parts) == 2:
                        player_name = parts[1].strip()
                        new_goals.append(player_name)
                except Exception as e:
                    _LOGGER.debug(f"שגיאה בחילוץ שם השחקן: {e}")
        
        return new_goals[:goals_count]

    def _dispatch_goal_event(self, scoring_team, opponent_team, goals_count, home_score, away_score, match, goal_scorers=None):
        """שידור אירוע שער ל-Home Assistant"""
        try:
            player_name = goal_scorers[0] if goal_scorers and len(goal_scorers) > 0 else "N/A"
            
            event_data = {
                "team": scoring_team,
                "opponent": opponent_team,
                "goals_scored": goals_count,
                "player": player_name,
                "home_team": match.get("home_team", "N/A"),
                "away_team": match.get("away_team", "N/A"),
                "home_score": home_score,
                "away_score": away_score,
                "venue": match.get("venue", "N/A"),
                "match_status": match.get("status", "N/A"),
                "season_info": match.get("season_info", "N/A"),
                "league_name": match.get("league_name", "N/A"),
                "competition_code": self._code,
                "sensor_name": self._name,
            }
            self.hass.bus.fire("calcio_live_goal", event_data)
            _LOGGER.info(f"שער זוהה! {scoring_team} כבש {goals_count} שער/ים. שחקן: {player_name}. תוצאה: {home_score}-{away_score}")
        except Exception as e:
            _LOGGER.error(f"שגיאה בשידור אירוע שער: {e}")

    def _detect_and_dispatch_cards(self, matches):
        """זיהוי כרטיסים צהובים ואדומים ושידור אירועים"""
        live_matches = [m for m in matches if m.get("state") == "in"]
        
        for match in live_matches:
            match_id = f"{match.get('home_team', 'N/A')}_{match.get('away_team', 'N/A')}"
            match_details = match.get("match_details", [])
            
            # אם זו הפעם הראשונה שאנו רואים משחק זה, שמור את הפרטים
            if match_id not in self._previous_match_details:
                self._previous_match_details[match_id] = match_details.copy()
                continue
            
            prev_details = self._previous_match_details[match_id]
            
            # בדיקת פרטים חדשים
            for detail in match_details:
                if detail not in prev_details:
                    if "Yellow Card" in detail:
                        self._dispatch_card_event("yellow", detail, match)
                    elif "Red Card" in detail:
                        self._dispatch_card_event("red", detail, match)
            
            # עדכון הפרטים
            self._previous_match_details[match_id] = match_details.copy()

    def _dispatch_card_event(self, card_type, detail_str, match):
        """שידור אירוע כרטיס"""
        try:
            # פרסור: "Yellow Card - 27': Destiny Udogie" או "Red Card - 29': Cristian Romero"
            parts = detail_str.split("': ")
            minute = parts[0].split(" - ")[1] if " - " in parts[0] else "N/A"
            player = parts[1] if len(parts) > 1 else "N/A"
            
            event_type = f"calcio_live_{card_type}_card"
            event_data = {
                "card_type": card_type.upper(),
                "player": player,
                "minute": minute,
                "home_team": match.get("home_team", "N/A"),
                "away_team": match.get("away_team", "N/A"),
                "home_score": match.get("home_score", "N/A"),
                "away_score": match.get("away_score", "N/A"),
                "venue": match.get("venue", "N/A"),
                "match_status": match.get("status", "N/A"),
                "season_info": match.get("season_info", "N/A"),
                "league_name": match.get("league_name", "N/A"),
                "competition_code": self._code,
                "sensor_name": self._name,
            }
            self.hass.bus.fire(event_type, event_data)
            _LOGGER.info(f"כרטיס זוהה! {card_type.upper()} בדקה {minute} | {player}")
        except Exception as e:
            _LOGGER.error(f"שגיאה בשידור אירוע כרטיס: {e}")

    def _detect_and_dispatch_match_finished(self, matches):
        """זיהוי סיום משחק ושידור אירוע"""
        finished_matches = [m for m in matches if m.get("state") == "post"]
        
        for match in finished_matches:
            match_id = f"{match.get('home_team', 'N/A')}_{match.get('away_team', 'N/A')}"
            
            # שידור האירוע פעם אחת בלבד לכל משחק
            if match_id not in self._match_finished_dispatched:
                self._dispatch_match_finished_event(match)
                self._match_finished_dispatched.add(match_id)
                _LOGGER.info(f"אירוע סיום משחק שודר עבור: {match_id}")

    def _dispatch_match_finished_event(self, match):
        """שידור אירוע סיום משחק"""
        try:
            goal_scorers = self._extract_all_goal_scorers(match.get("match_details", []))
            
            event_data = {
                "home_team": match.get("home_team", "N/A"),
                "away_team": match.get("away_team", "N/A"),
                "home_score": match.get("home_score", "N/A"),
                "away_score": match.get("away_score", "N/A"),
                "final_status": match.get("status", "N/A"),
                "venue": match.get("venue", "N/A"),
                "match_status": match.get("status", "N/A"),
                "date": match.get("date", "N/A"),
                "competition_code": self._code,
                "season_info": match.get("season_info", "N/A"),
                "league_name": match.get("league_name", "N/A"),
                "goal_scorers": goal_scorers,
                "goal_scorers_str": ", ".join(goal_scorers) if goal_scorers else "N/A",
                "sensor_name": self._name,
            }
            self.hass.bus.fire("calcio_live_match_finished", event_data)
            _LOGGER.info(f"משחק הסתיים! {match.get('home_team', 'N/A')} {match.get('home_score', '?')} - {match.get('away_score', '?')} {match.get('away_team', 'N/A')}. כובשים: {', '.join(goal_scorers)}")
        except Exception as e:
            _LOGGER.error(f"שגיאה בשידור אירוע סיום משחק: {e}")

    def _extract_all_goal_scorers(self, match_details):
        """חילוץ שמות כל השחקנים שכבשו שערים מרשימת פרטי המשחק"""
        goal_scorers = []
        
        for detail in match_details:
            if "Goal" in detail:
                # פורמט: "Goal - 38': Bryan Mbeumo"
                try:
                    parts = detail.split("': ")
                    if len(parts) == 2:
                        player_name = parts[1].strip()
                        goal_scorers.append(player_name)
                except Exception as e:
                    _LOGGER.debug(f"שגיאה בחילוץ שם השחקן: {e}")
        
        return goal_scorers

    def _get_minutes_until(self, match_datetime):
        """חישוב הדקות עד למשחק"""
        try:
            if not match_datetime:
                return None
            user_timezone = self.hass.config.time_zone
            from zoneinfo import ZoneInfo
            local_tz = ZoneInfo(user_timezone)
            now = datetime.now(local_tz)
            delta = match_datetime - now
            minutes = int(delta.total_seconds() / 60)
            return minutes
        except Exception as e:
            _LOGGER.debug(f"שגיאה בחישוב דקות: {e}")
            return None

    def _compute_next_match_attributes(self, match):
        """חישוב תכונות המשחק הבא"""
        if not match:
            return {}
        
        match_datetime = self._parse_match_datetime(match.get("date"))
        
        return {
            "next_match_home_team": match.get("home_team", "N/A"),
            "next_match_away_team": match.get("away_team", "N/A"),
            "next_match_home_logo": match.get("home_logo", "N/A"),
            "next_match_away_logo": match.get("away_logo", "N/A"),
            "next_match_home_score": match.get("home_score", "N/A"),
            "next_match_away_score": match.get("away_score", "N/A"),
            "next_match_date": match.get("date", "N/A"),
            "next_match_datetime_iso": match_datetime.isoformat() if match_datetime else "N/A",
            "next_match_minutes_until": self._get_minutes_until(match_datetime),
            "next_match_status": match.get("state", "N/A"),
            "next_match_description": match.get("status", "N/A"),
            "next_match_venue": match.get("venue", "N/A"),
            "next_match_period": match.get("period", "N/A"),
            "next_match_clock": match.get("clock", "N/A"),
            "next_match_home_form": match.get("home_form", "N/A"),
            "next_match_away_form": match.get("away_form", "N/A"),
            "next_match_season_info": match.get("season_info", "N/A"),
        }

    def _compute_live_match_attributes(self, matches):
        """חישוב תכונות המשחק החי אם קיים"""
        live_matches = [m for m in matches if m.get("state") == "in"]
        if not live_matches:
            return {}
        
        match = live_matches[0]
        return {
            "live_match_home_team": match.get("home_team", "N/A"),
            "live_match_away_team": match.get("away_team", "N/A"),
            "live_match_home_logo": match.get("home_logo", "N/A"),
            "live_match_away_logo": match.get("away_logo", "N/A"),
            "live_match_home_score": match.get("home_score", "N/A"),
            "live_match_away_score": match.get("away_score", "N/A"),
            "live_match_date": match.get("date", "N/A"),
            "live_match_status": "in",
            "live_match_description": match.get("status", "N/A"),
            "live_match_venue": match.get("venue", "N/A"),
            "live_match_period": match.get("period", "N/A"),
            "live_match_clock": match.get("clock", "N/A"),
            "live_match_home_form": match.get("home_form", "N/A"),
            "live_match_away_form": match.get("away_form", "N/A"),
        }

    def _compute_all_matches_attributes(self, matches):
        """חישוב תכונות לכל המשחקים"""
        self._detect_and_dispatch_goals(matches)
        self._detect_and_dispatch_cards(matches)
        self._detect_and_dispatch_match_finished(matches)
        
        computed = {}
        
        # מידע על משחק חי אם קיים
        live_matches = [m for m in matches if m.get("state") == "in"]
        if live_matches:
            computed.update(self._compute_live_match_attributes(matches))
            computed["has_live_match"] = True
        else:
            computed["has_live_match"] = False
        
        # מידע על המשחק הבא
        upcoming_matches = [m for m in matches if m.get("state") == "pre"]
        if upcoming_matches:
            computed.update(self._compute_next_match_attributes(upcoming_matches[0]))
            computed["has_upcoming_match"] = True
        else:
            computed["has_upcoming_match"] = False
        
        # מידע על המשחק האחרון שהסתיים (48 שעות אחרונות)
        from .sensori.scoreboard import is_within_last_48_hours
        recent_finished_matches = [m for m in matches
            if m.get("state") == "post" and is_within_last_48_hours(m.get("date"))
        ]
        if recent_finished_matches:
            last_match = recent_finished_matches[0]
            computed.update({
                "last_match_home_team": last_match.get("home_team", "N/A"),
                "last_match_away_team": last_match.get("away_team", "N/A"),
                "last_match_home_logo": last_match.get("home_logo", "N/A"),
                "last_match_away_logo": last_match.get("away_logo", "N/A"),
                "last_match_home_score": last_match.get("home_score", "N/A"),
                "last_match_away_score": last_match.get("away_score", "N/A"),
                "last_match_date": last_match.get("date", "N/A"),
                "last_match_venue": last_match.get("venue", "N/A"),
                "has_recent_match": True,
            })
        else:
            computed["has_recent_match"] = False
        
        # סיכומים
        computed["total_matches"] = len(matches)
        computed["live_matches_count"] = len(live_matches)
        computed["upcoming_matches_count"] = len(upcoming_matches)
        computed["finished_matches_count"] = len([m for m in matches if m.get("state") == "post"])
        
        return computed

    def _process_data(self, data):
        from .sensori.scoreboard import process_match_data

        if self._sensor_type == "standings":
            from .sensori.classifica import classifica_data
            processed_data = classifica_data(data)
            self._state = "טבלת דירוג"
            self._attributes = processed_data

        elif self._sensor_type == "match_day":
            match_data = process_match_data(data, self.hass, start_date=self._start_date.strftime("%Y-%m-%d"), end_date=self._end_date.strftime("%Y-%m-%d"))
            self._state = "משחקי השבוע"
            self._attributes = {
                "league_info": match_data.get("league_info", "N/A"),
                "matches": match_data.get("matches", [])
            }
        
        elif self._sensor_type in ["team_matches", "team_match", "team_matches_mixed", "all_matches_today"]:
            def get_team_match_data(next_match_only=False):
                return process_match_data(
                    data,
                    self.hass,
                    team_name=self._team_name,
                    next_match_only=next_match_only,
                    start_date=self._start_date.strftime("%Y-%m-%d"),
                    end_date=self._end_date.strftime("%Y-%m-%d")
                )
            
            if self._sensor_type in ["team_matches", "team_matches_mixed", "all_matches_today"]:
                match_data = get_team_match_data()
                matches = match_data.get("matches", []) or []
                next_match = match_data.get("next_match")

                if matches:
                    # עדיפות 1: משחק חי
                    live_matches = [m for m in matches if m.get("state") == "in"]
                    if live_matches:
                        lm = live_matches[0]
                        self._state = f"🔴 {lm.get('home_team','?')} {lm.get('home_score','?')} - {lm.get('away_score','?')} {lm.get('away_team','?')} ({lm.get('clock','')})"
                    else:
                        # עדיפות 2: המשחק האחרון שהסתיים (הכי עדכני)
                        finished_matches = [m for m in matches if m.get("state") == "post"]
                        if finished_matches:
                            fm = finished_matches[0]
                            self._state = f"✅ {fm.get('home_team','?')} {fm.get('home_score','?')} - {fm.get('away_score','?')} {fm.get('away_team','?')}"
                        else:
                            # עדיפות 3: המשחק הבא המתוכנן
                            upcoming_matches = [m for m in matches if m.get("state") == "pre"]
                            if upcoming_matches:
                                um = upcoming_matches[0]
                                self._state = f"⏳ {um.get('home_team','?')} נגד {um.get('away_team','?')} ({um.get('date','?')})"
                            else:
                                self._state = f"📊 {len(matches)} משחקים זמינים"
                else:
                    self._state = "אין משחקים זמינים"

                computed_attrs = self._compute_all_matches_attributes(matches)

                self._attributes = {
                    "league_info": match_data.get("league_info", "N/A"),
                    "team_name": match_data.get("team_name", "N/A"),
                    "team_logo": match_data.get("team_logo", "N/A"),
                    "matches": matches,
                    "next_match": next_match,
                    **computed_attrs,
                }

            elif self._sensor_type == "team_match":
                team_match = get_team_match_data(next_match_only=True)
                matches = team_match.get("matches", []) or []
                next_match = team_match.get("next_match")

                if next_match:
                    if next_match.get("state") == "in":
                        self._state = f"{next_match.get('home_score','?')} - {next_match.get('away_score','?')} ({next_match.get('clock','')})"
                    else:
                        self._state = f"המשחק הבא: {next_match.get('home_team','N/A')} נגד {next_match.get('away_team','N/A')}"
                else:
                    self._state = "אין משחקים זמינים"

                computed_attrs = self._compute_next_match_attributes(next_match) if next_match else {}

                self._attributes = {
                    **team_match,
                    "matches": matches,
                    "next_match": next_match,
                    **computed_attrs,
                }

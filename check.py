from datetime import datetime, timezone
import json
import sys
import time
import requests
from api import fetch_full_match, session
from config import API_DELAY, MAX_RETRIES, REQUEST_TIMEOUT, CONNECT_TIMEOUT

def load_heroes():
    """Load heroes data from heroes.json"""
    try:
        with open('heroes.json', 'r', encoding='utf-8') as f:
            heroes_data = json.load(f)
        return {hero['id']: hero['localized_name'] for hero in heroes_data}
    except FileNotFoundError:
        print("[ERROR] heroes.json file not found")
        return {}

def get_hero_id_by_name(hero_name, heroes_dict):
    """Get hero ID by localized name (case insensitive)"""
    hero_name = hero_name.lower()
    for hero_id, name in heroes_dict.items():
        if name.lower() == hero_name:
            return hero_id
    return None

def fetch_ranked_match_ids(account_id, limit=20, offset=0, hero_id=None, start_date=None, end_date=None):
    """Fetch ranked matches only with optional filters."""
    # Build URL with lobby_type=7 for ranked matches only
    url = f"https://api.opendota.com/api/players/{account_id}/matches?limit={limit}&offset={offset}&lobby_type=7"
    
    # Add optional filters
    if hero_id:
        url += f"&hero_id={hero_id}"
    
    if start_date:
        date_param = int(start_date.timestamp())
        url += f"&date={date_param}"
    
    for attempt in range(MAX_RETRIES):
        try:
            r = session.get(url, timeout=(CONNECT_TIMEOUT, REQUEST_TIMEOUT))
            r.raise_for_status()
            matches = r.json()
            if not isinstance(matches, list):
                raise ValueError(f"Unexpected response format: {type(matches)}")

            # Filter by end date if specified
            filtered_matches = []
            for m in matches:
                match_time = datetime.fromtimestamp(m.get("start_time", 0), tz=timezone.utc)
                if end_date and match_time > end_date:
                    continue
                filtered_matches.append(m)
            
            time.sleep(API_DELAY)
            return filtered_matches
            
        except requests.exceptions.Timeout:
            wait = min(10, 2 ** attempt)
            print(f"[WARN] Timeout for {account_id} (attempt {attempt+1}/{MAX_RETRIES}), waiting {wait}s...")
            time.sleep(wait)
            
        except requests.exceptions.ConnectionError as e:
            wait = min(10, 2 ** attempt)
            print(f"[WARN] Connection error for {account_id}, waiting {wait}s...")
            time.sleep(wait)
            
        except Exception as e:
            if attempt == MAX_RETRIES - 1:
                print(f"[ERROR] Fetch matches for {account_id}: {e}")
            time.sleep(min(5, 2 ** attempt))
    
    return []

def search_steam_player(account_id, start_date=None, end_date=None, hero_id=None):
    """
    Search for a Steam player's RANKED match statistics within a time period and optional hero filter.
    
    Args:
        account_id: Steam account ID
        start_date: Start date as datetime object
        end_date: End date as datetime object  
        hero_id: Optional hero ID to filter by
        
    Returns:
        Dictionary with wins, losses, win_rate, total_matches
    """
    print(f"[INFO] Searching for RANKED matches for player {account_id}")
    if hero_id:
        heroes = load_heroes()
        hero_name = heroes.get(hero_id, f"ID {hero_id}")
        print(f"[INFO] Filtering by hero: {hero_name}")
    
    if start_date:
        print(f"[INFO] From: {start_date.strftime('%Y-%m-%d')}")
    if end_date:
        print(f"[INFO] To: {end_date.strftime('%Y-%m-%d')}")
    
    wins = 0
    losses = 0
    total_matches = 0
    offset = 0
    
    while True:
        # Fetch ranked matches only
        ranked_matches = fetch_ranked_match_ids(account_id, limit=20, offset=offset, hero_id=hero_id, start_date=start_date, end_date=end_date)
        if not ranked_matches:
            break
            
        print(f"[INFO] Processing {len(ranked_matches)} ranked matches (offset: {offset})")
        
        for match in ranked_matches:
            # Extract data from the ranked match response
            match_id = match.get('match_id')
            radiant_win = match.get('radiant_win', False)
            player_slot = match.get('player_slot')
            
            # Additional verification by fetching full match data
            match_data = fetch_full_match(match_id)
            if not match_data:
                continue
                
            # Double-check this is actually a ranked match
            lobby_type = match_data.get('lobby_type')
            if lobby_type != 7:
                print(f"[WARN] Skipping non-ranked match {match_id} (lobby_type: {lobby_type})")
                continue
                
            # Check if match is within time period (already filtered by API, but double-check)
            match_time = datetime.fromtimestamp(match_data.get('start_time', 0), tz=timezone.utc)
            
            if start_date and match_time < start_date:
                continue
            if end_date and match_time > end_date:
                continue
            
            # Determine win/loss
            # player_slot: 0-127 are Radiant, 128-255 are Dire
            # radiant_win: True if Radiant won
            is_radiant = player_slot < 128 if player_slot is not None else False
            
            if is_radiant == radiant_win:
                wins += 1
            else:
                losses += 1
            
            total_matches += 1
        
        offset += 20
        
        # Safety break to avoid infinite loops
        if offset > 1000:
            print("[WARN] Reached safety limit of 1000 matches")
            break
    
    win_rate = (wins / total_matches * 100) if total_matches > 0 else 0
    
    return {
        'wins': wins,
        'losses': losses,
        'total_matches': total_matches,
        'win_rate': win_rate
    }

def interactive_search():
    """Interactive command-line interface for searching player stats"""
    print("=== Dota 2 RANKED Player Stats Search ===\n")
    
    # Get Steam ID
    while True:
        try:
            account_id = input("Enter Steam ID (account ID): ").strip()
            if account_id.isdigit():
                account_id = int(account_id)
                break
            else:
                print("Please enter a valid numeric Steam ID")
        except KeyboardInterrupt:
            print("\nExiting...")
            return
    
    # Get time period
    start_date = None
    end_date = None
    
    print("\nTime period (leave empty for all time):")
    
    while True:
        start_input = input("Start date (YYYY-MM-DD, or press Enter): ").strip()
        if not start_input:
            break
        try:
            start_date = datetime.strptime(start_input, '%Y-%m-%d').replace(tzinfo=timezone.utc)
            break
        except ValueError:
            print("Invalid date format. Use YYYY-MM-DD")
    
    while True:
        end_input = input("End date (YYYY-MM-DD, or press Enter): ").strip()
        if not end_input:
            break
        try:
            end_date = datetime.strptime(end_input, '%Y-%m-%d').replace(tzinfo=timezone.utc)
            break
        except ValueError:
            print("Invalid date format. Use YYYY-MM-DD")
    
    # Get hero filter
    hero_id = None
    heroes = load_heroes()
    
    if heroes:
        print("\nHero filter (optional):")
        hero_input = input("Enter hero name (or press Enter for all heroes): ").strip()
        if hero_input:
            hero_id = get_hero_id_by_name(hero_input, heroes)
            if not hero_id:
                print(f"Hero '{hero_input}' not found. Showing stats for all heroes.")
            else:
                print(f"Filtering by: {heroes[hero_id]}")
    
    # Search
    print(f"\nSearching for RANKED matches for player {account_id}...")
    results = search_steam_player(account_id, start_date, end_date, hero_id)
    
    # Display results
    print(f"\n=== Results ===")
    print(f"Total matches: {results['total_matches']}")
    print(f"Wins: {results['wins']}")
    print(f"Losses: {results['losses']}")
    print(f"Win rate: {results['win_rate']:.1f}%")

def main():
    """Main entry point"""
    if len(sys.argv) > 1:
        # Command line mode: python check.py <steam_id> [start_date] [end_date] [hero_name]
        try:
            account_id = int(sys.argv[1])
        except ValueError:
            print("Error: Steam ID must be a number")
            return
        
        start_date = None
        end_date = None
        hero_id = None
        
        if len(sys.argv) > 2 and sys.argv[2]:
            try:
                start_date = datetime.strptime(sys.argv[2], '%Y-%m-%d').replace(tzinfo=timezone.utc)
            except ValueError:
                print("Error: Invalid start date format. Use YYYY-MM-DD")
                return
        
        if len(sys.argv) > 3 and sys.argv[3]:
            try:
                end_date = datetime.strptime(sys.argv[3], '%Y-%m-%d').replace(tzinfo=timezone.utc)
            except ValueError:
                print("Error: Invalid end date format. Use YYYY-MM-DD")
                return
        
        if len(sys.argv) > 4 and sys.argv[4]:
            heroes = load_heroes()
            hero_id = get_hero_id_by_name(sys.argv[4], heroes)
            if not hero_id:
                print(f"Error: Hero '{sys.argv[4]}' not found")
                return
        
        results = search_steam_player(account_id, start_date, end_date, hero_id)
        
        print(f"\n=== RANKED Results for Steam ID {account_id} ===")
        print(f"Total matches: {results['total_matches']}")
        print(f"Wins: {results['wins']}")
        print(f"Losses: {results['losses']}")
        print(f"Win rate: {results['win_rate']:.1f}%")
        
    else:
        # Interactive mode
        interactive_search()

if __name__ == "__main__":
    main()

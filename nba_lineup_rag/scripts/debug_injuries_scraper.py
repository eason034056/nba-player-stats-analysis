#!/usr/bin/env python3
"""
debug_injuries_scraper.py - Debug script for Injuries Scraping

這個腳本用於診斷 injuries_pages.py 的問題：
1. 抓取 ESPN 和 CBS 的 injuries 頁面
2. 儲存原始 HTML 供手動檢查
3. 輸出解析過程的每個步驟，找出哪裡出錯
4. 顯示球隊與球員的對應關係

使用方法:
    python scripts/debug_injuries_scraper.py
    python scripts/debug_injuries_scraper.py --espn-only
    python scripts/debug_injuries_scraper.py --cbs-only
    python scripts/debug_injuries_scraper.py --save-html
"""

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# 加入 project root 到 path，讓 import 正確運作
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config import get_config, normalize_team_name, NBA_TEAMS


def create_session():
    """建立 HTTP session"""
    config = get_config()
    session = requests.Session()
    session.headers.update({
        "User-Agent": config.user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    })
    return session


def fetch_page(session, url: str) -> str:
    """抓取網頁並回傳 HTML"""
    print(f"\n{'='*60}")
    print(f"Fetching: {url}")
    print(f"{'='*60}")
    
    try:
        response = session.get(url, timeout=30)
        response.raise_for_status()
        print(f"✓ Status: {response.status_code}")
        print(f"✓ Content-Length: {len(response.text)} chars")
        return response.text
    except Exception as e:
        print(f"✗ Error: {e}")
        return ""


def save_html(html: str, filename: str):
    """儲存 HTML 到 logs 目錄"""
    logs_dir = project_root / "logs"
    logs_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = logs_dir / f"{filename}_{timestamp}.html"
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)
    
    print(f"✓ HTML saved to: {filepath}")
    return filepath


def debug_espn(html: str, verbose: bool = True):
    """
    Debug ESPN injuries 頁面的解析
    
    這個函數會一步步顯示解析過程，幫助找出問題
    """
    print(f"\n{'='*60}")
    print("DEBUG: ESPN Injuries Page Parsing")
    print(f"{'='*60}")
    
    soup = BeautifulSoup(html, "lxml")
    
    # Step 1: 找所有 ResponsiveTable
    print("\n[Step 1] Finding all 'ResponsiveTable' divs...")
    team_sections = soup.find_all("div", class_="ResponsiveTable")
    print(f"   Found: {len(team_sections)} sections")
    
    if len(team_sections) == 0:
        print("\n   ⚠️  WARNING: No ResponsiveTable found!")
        print("   Let's try other selectors...")
        
        # 嘗試其他可能的 selector
        alt_selectors = [
            ("table", {}),
            ("div", {"class": "Table"}),
            ("div", {"class": re.compile(r"Table", re.I)}),
            ("div", {"class": re.compile(r"injury", re.I)}),
        ]
        
        for tag, attrs in alt_selectors:
            found = soup.find_all(tag, attrs)
            print(f"   - {tag} {attrs}: found {len(found)}")
    
    # Step 2: 找所有 Table__Title (球隊標題)
    print("\n[Step 2] Finding all 'Table__Title' divs...")
    all_titles = soup.find_all("div", class_="Table__Title")
    print(f"   Found: {len(all_titles)} titles")
    
    if all_titles:
        print("   Titles found:")
        for i, title in enumerate(all_titles):
            text = title.get_text(strip=True)
            normalized = normalize_team_name(text)
            status = "✓" if normalized else "✗ (cannot normalize)"
            print(f"      [{i}] '{text}' -> {normalized} {status}")
    else:
        print("\n   ⚠️  WARNING: No Table__Title found!")
        print("   Let's search for team names in other elements...")
        
        # 搜尋可能包含球隊名稱的元素
        for team_code, aliases in list(NBA_TEAMS.items())[:5]:  # 只測試前5隊
            team_name = aliases[0]  # e.g., "Atlanta Hawks"
            found = soup.find(string=re.compile(team_name, re.I))
            if found:
                print(f"   - Found '{team_name}' in: {found.parent.name} (class={found.parent.get('class')})")
    
    # Step 3: 解析每個 section
    print("\n[Step 3] Parsing each section...")
    
    results = []
    
    for i, section in enumerate(team_sections):
        print(f"\n   --- Section {i} ---")
        
        # FIXED: 用 find() 而不是 find_previous()
        # Table__Title 是 ResponsiveTable 的子元素
        team_header = section.find("div", class_="Table__Title")
        team_name = ""
        if team_header:
            team_name = team_header.get_text(strip=True)
            print(f"   team_header (find): '{team_name}' ✓")
        else:
            print(f"   team_header (find): NOT FOUND ⚠️")
        
        team_code = normalize_team_name(team_name) or team_name
        print(f"   team_code (after normalize): '{team_code}'")
        
        # 找 table
        table = section.find("table") or section.find("tbody")
        if table:
            print(f"   table found: {table.name}")
        else:
            print(f"   table: NOT FOUND ⚠️")
            continue
        
        # 找所有 rows
        rows = section.find_all("tr")
        print(f"   rows found: {len(rows)}")
        
        # 解析每一 row
        for j, row in enumerate(rows):
            # 跳過 header
            if row.find("th"):
                if verbose:
                    print(f"      [row {j}] HEADER (skipped)")
                continue
            
            cells = row.find_all("td")
            if len(cells) >= 2:
                player_name = cells[0].get_text(strip=True) if len(cells) > 0 else ""
                position = cells[1].get_text(strip=True) if len(cells) > 1 else ""
                injury = cells[2].get_text(strip=True) if len(cells) > 2 else ""
                status = cells[3].get_text(strip=True) if len(cells) > 3 else ""
                
                result = {
                    "team": team_code,
                    "player": player_name,
                    "position": position,
                    "injury": injury,
                    "status": status,
                }
                results.append(result)
                
                if verbose:
                    print(f"      [row {j}] {team_code} | {player_name} | {position} | {injury} | {status}")
    
    # Step 4: 總結
    print(f"\n{'='*60}")
    print("SUMMARY: ESPN Parsing Results")
    print(f"{'='*60}")
    print(f"Total records parsed: {len(results)}")
    
    # 統計每隊的球員數
    team_counts = {}
    for r in results:
        team = r["team"]
        team_counts[team] = team_counts.get(team, 0) + 1
    
    print(f"\nPlayers per team:")
    for team, count in sorted(team_counts.items()):
        # 檢查是否是有效的球隊代碼
        is_valid = team in NBA_TEAMS
        status = "✓" if is_valid else "⚠️ INVALID TEAM CODE"
        print(f"   {team}: {count} players {status}")
    
    # 顯示可疑記錄
    suspicious = [r for r in results if r["team"] not in NBA_TEAMS or not r["team"]]
    if suspicious:
        print(f"\n⚠️  SUSPICIOUS RECORDS (invalid team):")
        for r in suspicious[:10]:  # 最多顯示 10 筆
            print(f"   {r}")
    
    return results


def debug_cbs(html: str, verbose: bool = True):
    """
    Debug CBS injuries 頁面的解析
    """
    print(f"\n{'='*60}")
    print("DEBUG: CBS Injuries Page Parsing")
    print(f"{'='*60}")
    
    soup = BeautifulSoup(html, "lxml")
    
    # Step 1: 找 TableBaseWrapper
    print("\n[Step 1] Finding 'TableBaseWrapper' divs...")
    team_sections = soup.find_all("div", class_="TableBaseWrapper")
    print(f"   Found: {len(team_sections)} sections")
    
    if len(team_sections) == 0:
        print("\n   ⚠️  WARNING: No TableBaseWrapper found!")
        print("   Trying fallback: all <table> elements...")
        team_sections = soup.find_all("table")
        print(f"   Found: {len(team_sections)} tables")
    
    # Step 2: 找可能的球隊標題
    print("\n[Step 2] Looking for team headers...")
    
    # CBS 可能的標題 class
    possible_headers = soup.find_all(
        ["h3", "h4", "div"], 
        class_=re.compile(r"team|header|title", re.I)
    )
    print(f"   Found: {len(possible_headers)} possible headers")
    
    for i, h in enumerate(possible_headers[:10]):  # 最多顯示 10 個
        text = h.get_text(strip=True)[:50]  # 截斷長文字
        print(f"      [{i}] <{h.name}> class={h.get('class')}: '{text}'")
    
    # Step 3: 解析每個 section
    print("\n[Step 3] Parsing each section...")
    
    results = []
    current_team = ""
    
    for i, section in enumerate(team_sections):
        print(f"\n   --- Section {i} ---")
        
        # FIXED: 用 find() 而不是 find_previous()
        # TeamName span 是 TableBaseWrapper 的子元素
        team_span = section.find("span", class_="TeamName")
        if team_span:
            team_text = team_span.get_text(strip=True)
            print(f"   team_span (find): '{team_text}' ✓")
            normalized = normalize_team_name(team_text)
            if normalized:
                current_team = normalized
                print(f"   normalized to: '{current_team}' ✓")
            else:
                print(f"   normalize failed ⚠️")
                current_team = ""
        else:
            print(f"   team_span (find): NOT FOUND ⚠️")
            current_team = ""
        
        # 解析 rows
        rows = section.find_all("tr")
        print(f"   rows found: {len(rows)}")
        
        for j, row in enumerate(rows):
            if row.find("th"):
                if verbose:
                    print(f"      [row {j}] HEADER (skipped)")
                continue
            
            cells = row.find_all("td")
            if len(cells) >= 2:
                player_name = cells[0].get_text(strip=True) if len(cells) > 0 else ""
                position = cells[1].get_text(strip=True) if len(cells) > 1 else ""
                injury = cells[3].get_text(strip=True) if len(cells) > 3 else ""
                status = cells[4].get_text(strip=True) if len(cells) > 4 else ""
                
                result = {
                    "team": current_team,
                    "player": player_name,
                    "position": position,
                    "injury": injury,
                    "status": status,
                }
                results.append(result)
                
                if verbose:
                    print(f"      [row {j}] {current_team} | {player_name} | {position}")
    
    # Step 4: 總結
    print(f"\n{'='*60}")
    print("SUMMARY: CBS Parsing Results")
    print(f"{'='*60}")
    print(f"Total records parsed: {len(results)}")
    
    team_counts = {}
    for r in results:
        team = r["team"]
        team_counts[team] = team_counts.get(team, 0) + 1
    
    print(f"\nPlayers per team:")
    for team, count in sorted(team_counts.items()):
        is_valid = team in NBA_TEAMS
        status = "✓" if is_valid else "⚠️ INVALID TEAM CODE"
        print(f"   {team}: {count} players {status}")
    
    suspicious = [r for r in results if r["team"] not in NBA_TEAMS or not r["team"]]
    if suspicious:
        print(f"\n⚠️  SUSPICIOUS RECORDS (invalid team):")
        for r in suspicious[:10]:
            print(f"   {r}")
    
    return results


def analyze_html_structure(html: str, source: str):
    """
    分析 HTML 結構，找出可能包含傷兵資料的元素
    """
    print(f"\n{'='*60}")
    print(f"STRUCTURE ANALYSIS: {source}")
    print(f"{'='*60}")
    
    soup = BeautifulSoup(html, "lxml")
    
    # 找所有的 table
    tables = soup.find_all("table")
    print(f"\n[Tables] Found {len(tables)} <table> elements")
    
    for i, table in enumerate(tables[:5]):  # 最多看 5 個
        classes = table.get("class", [])
        rows = table.find_all("tr")
        print(f"   Table {i}: class={classes}, rows={len(rows)}")
        
        # 顯示第一個非 header row 的結構
        for row in rows:
            if not row.find("th"):
                cells = row.find_all("td")
                cell_texts = [c.get_text(strip=True)[:20] for c in cells]
                print(f"      Sample row cells: {cell_texts}")
                break
    
    # 找所有包含 "injury" 的 class
    print(f"\n[Injury-related classes]")
    injury_elements = soup.find_all(class_=re.compile(r"injury", re.I))
    classes_found = set()
    for el in injury_elements:
        classes_found.update(el.get("class", []))
    
    for cls in sorted(classes_found):
        print(f"   .{cls}")
    
    # 找 NBA 球隊名稱出現的位置
    print(f"\n[Team name locations]")
    sample_teams = ["Lakers", "Celtics", "Warriors", "Heat", "Knicks"]
    for team in sample_teams:
        matches = soup.find_all(string=re.compile(team, re.I))
        if matches:
            parent = matches[0].parent
            print(f"   '{team}' found in <{parent.name}> class={parent.get('class')}")


def main():
    parser = argparse.ArgumentParser(description="Debug injuries scraper")
    parser.add_argument("--espn-only", action="store_true", help="Only debug ESPN")
    parser.add_argument("--cbs-only", action="store_true", help="Only debug CBS")
    parser.add_argument("--save-html", action="store_true", help="Save raw HTML to logs/")
    parser.add_argument("--analyze", action="store_true", help="Analyze HTML structure")
    parser.add_argument("--quiet", "-q", action="store_true", help="Less verbose output")
    args = parser.parse_args()
    
    config = get_config()
    session = create_session()
    
    verbose = not args.quiet
    
    print(f"NBA Lineup RAG - Injuries Scraper Debugger")
    print(f"Time: {datetime.now().isoformat()}")
    
    # ESPN
    if not args.cbs_only:
        espn_html = fetch_page(session, config.ESPN_INJURIES_URL)
        
        if espn_html:
            if args.save_html:
                save_html(espn_html, "espn_injuries_debug")
            
            if args.analyze:
                analyze_html_structure(espn_html, "ESPN")
            
            debug_espn(espn_html, verbose=verbose)
    
    # CBS
    if not args.espn_only:
        cbs_html = fetch_page(session, config.CBS_INJURIES_URL)
        
        if cbs_html:
            if args.save_html:
                save_html(cbs_html, "cbs_injuries_debug")
            
            if args.analyze:
                analyze_html_structure(cbs_html, "CBS")
            
            debug_cbs(cbs_html, verbose=verbose)
    
    print(f"\n{'='*60}")
    print("Debug complete!")
    print(f"{'='*60}")
    print("\nNext steps:")
    print("1. Check if team names are being correctly matched")
    print("2. If HTML saved, manually inspect the structure")
    print("3. Look for ⚠️ warnings above to identify issues")


if __name__ == "__main__":
    main()

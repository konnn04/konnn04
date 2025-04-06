#!/usr/bin/python3

import asyncio
import json
import os
import re
from datetime import datetime, timedelta
import aiohttp
from bs4 import BeautifulSoup

from github_stats import Stats, Queries

async def fetch_additional_stats(queries: Queries) -> dict:
    """Fetch additional GitHub stats not available in the Stats class"""
    # Get current year and last year
    now = datetime.now()
    current_year = now.year
    last_year = current_year - 1
    
    # Define GraphQL query for additional stats including pinned repositories
    query = f"""
    {{
      viewer {{
        pullRequests(first: 0) {{
          totalCount
        }}
        issues(first: 0) {{
          totalCount
        }}
        repositoriesContributedTo(
          contributionTypes: [COMMIT, PULL_REQUEST, ISSUE, REPOSITORY]
          first: 0
          includeUserRepositories: false
          since: "{last_year}-01-01T00:00:00Z"
        ) {{
          totalCount
        }}
        contributionsCollection(from: "{current_year}-01-01T00:00:00Z") {{
          totalCommitContributions
          restrictedContributionsCount
        }}
        pinnedItems(first: 6, types: [REPOSITORY]) {{
          totalCount
          nodes {{
            ... on Repository {{
              name
              nameWithOwner
              description
              url
              stargazerCount
              forkCount
              primaryLanguage {{
                name
                color
              }}
              isPrivate
              updatedAt
            }}
          }}
        }}
      }}
      user(login: "{queries.username}") {{
        pinnedItems(first: 6, types: [REPOSITORY]) {{
          totalCount
          nodes {{
            ... on Repository {{
              name
              nameWithOwner
              description
              url
              stargazerCount
              forkCount
              primaryLanguage {{
                name
                color
              }}
              isPrivate
              updatedAt
            }}
          }}
        }}
      }}
    }}
    """
    
    result = await queries.query(query)
    data = result.get("data", {})
    viewer_data = data.get("viewer", {})
    
    # Try to get pinned items from viewer first, then from user object if available
    if not viewer_data.get("pinnedItems", {}).get("nodes", []):
        user_data = data.get("user", {})
        if user_data and user_data.get("pinnedItems", {}).get("nodes", []):
            viewer_data["pinnedItems"] = user_data.get("pinnedItems", {})
    
    return viewer_data

async def fetch_berrysauce_pinned(session: aiohttp.ClientSession, username: str) -> list:
    """Fetch pinned repositories from berrysauce.dev API"""
    try:
        async with session.get(f"https://pinned.berrysauce.dev/get/{username}", timeout=10) as response:
            if response.status == 200:
                data = await response.json()
                print(f"Berrysauce API response: {data.keys() if isinstance(data, dict) else 'Not a dict'}")
                return data.get("repos", []) if isinstance(data, dict) else []
            else:
                print(f"Berrysauce API returned status code: {response.status}")
                return []
    except Exception as e:
        print(f"Error fetching from berrysauce API: {e}")
        return []

async def scrape_pinned_repos(session: aiohttp.ClientSession, username: str) -> list:
    """Directly scrape pinned repositories from GitHub profile page"""
    try:
        print(f"Attempting to scrape pinned repos directly from GitHub profile for {username}...")
        
        async with session.get(f"https://github.com/{username}", timeout=30) as response:
            if response.status == 200:
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                # Try multiple different selectors that GitHub might be using
                selectors = [
                    'div[data-repository-hovercards-enabled] article.pinned-item-list-item',
                    'ol.d-flex.flex-wrap li.mb-3',
                    'div.js-pinned-items-reorder-container ol li',
                    'div.pinned-item-list-item-content',
                    '.js-pinned-items-reorder-container .pinned-item-list-item'
                ]
                
                pinned_items = []
                for selector in selectors:
                    items = soup.select(selector)
                    if items:
                        print(f"Found pinned items using selector: {selector}")
                        pinned_items = items
                        break
                
                if not pinned_items:
                    # Save HTML for debugging
                    with open("github_profile.html", "w", encoding="utf-8") as f:
                        f.write(html)
                    print("No pinned repositories found in GitHub profile HTML (saved profile HTML for debugging)")
                    return []
                    
                print(f"Found {len(pinned_items)} pinned repositories via HTML scraping")
                
                scraped_repos = []
                for item in pinned_items:
                    # Extract repo information
                    repo_name = item.select_one('span.repo').text.strip() if item.select_one('span.repo') else ""
                    repo_owner = username
                    
                    # Sometimes the owner/name might be in a different format
                    full_name_elem = item.select_one('a[href*="/"]')
                    if full_name_elem and '/' in full_name_elem.get('href', ''):
                        full_path = full_name_elem.get('href', '').strip('/')
                        parts = full_path.split('/')
                        if len(parts) >= 2:
                            repo_owner = parts[0]
                            repo_name = parts[1]
                    
                    # Extract description
                    description = item.select_one('p.pinned-item-desc')
                    description_text = description.text.strip() if description else ""
                    
                    # Extract language
                    language_elem = item.select_one('span[itemprop="programmingLanguage"]')
                    language = language_elem.text.strip() if language_elem else None
                    
                    # Extract language color
                    color_elem = item.select_one('span.repo-language-color')
                    color = color_elem.get('style', '').replace('background-color:', '').strip() if color_elem else '#000000'
                    
                    # Add to scraped repos
                    scraped_repos.append({
                        "name": repo_name,
                        "owner": repo_owner,
                        "description": description_text,
                        "language": language,
                        "color": color
                    })
                
                return scraped_repos
            else:
                print(f"GitHub profile page returned status code: {response.status}")
                return []
    except Exception as e:
        print(f"Error scraping GitHub profile: {e}")
        return []

async def export_stats_json() -> None:
    """Generate a JSON file with GitHub stats"""
    access_token = os.getenv("ACCESS_TOKEN")
    if not access_token:
        raise Exception("A personal access token is required to proceed!")
    
    user = os.getenv("GITHUB_ACTOR")
    if user is None:
        print("Warning: GITHUB_ACTOR not set, trying to use repository owner")
        user = "konnn04"  # Fallback to your username
        
    print(f"Generating JSON stats for user: {user}")
    
    exclude_repos = os.getenv("EXCLUDED")
    excluded_repos = (
        {x.strip() for x in exclude_repos.split(",")} if exclude_repos else None
    )
    exclude_langs = os.getenv("EXCLUDED_LANGS")
    excluded_langs = (
        {x.strip() for x in exclude_langs.split(",")} if exclude_langs else None
    )
    raw_ignore_forked_repos = os.getenv("EXCLUDE_FORKED_REPOS")
    ignore_forked_repos = (
        not not raw_ignore_forked_repos
        and raw_ignore_forked_repos.strip().lower() != "false"
    )
    
    async with aiohttp.ClientSession() as session:
        # Initialize Stats object from existing code
        s = Stats(
            user,
            access_token,
            session,
            exclude_repos=excluded_repos,
            exclude_langs=excluded_langs,
            ignore_forked_repos=ignore_forked_repos,
        )
        
        # Fetch additional stats using the same queries object
        additional_stats = await fetch_additional_stats(s.queries)
        
        # Debug output
        print(f"Additional stats keys: {list(additional_stats.keys())}")
        
        # Check for pinned items directly from GraphQL query
        pinned_items = additional_stats.get("pinnedItems", {})
        pinned_nodes = pinned_items.get("nodes", [])
        print(f"Pinned items found from GraphQL: {len(pinned_nodes)}")
        
        # If no pinned items found, try using the REST API as a fallback
        if not pinned_nodes:
            print("No pinned repositories found, trying REST API fallback...")
            
            # First, try the pinned items endpoint if available
            try:
                # First try to get pinned items from the user profile
                pinned_rest_query = f"/users/{user}/pinned"
                pinned_rest_result = await s.queries.query_rest(pinned_rest_query)
                if pinned_rest_result and isinstance(pinned_rest_result, list) and len(pinned_rest_result) > 0:
                    print(f"Found {len(pinned_rest_result)} pinned repositories via REST API")
                    # Format the REST API data to match the GraphQL format
                    pinned_nodes = [
                        {
                            "name": repo.get("name"),
                            "nameWithOwner": repo.get("full_name"),
                            "description": repo.get("description"),
                            "url": repo.get("html_url"),
                            "stargazerCount": repo.get("stargazers_count"),
                            "forkCount": repo.get("forks_count"),
                            "primaryLanguage": {
                                "name": repo.get("language"),
                                "color": "#" + format(hash(repo.get("language") or ""), '06x')[0:6]
                            } if repo.get("language") else None,
                            "isPrivate": repo.get("private"),
                            "updatedAt": repo.get("updated_at")
                        }
                        for repo in pinned_rest_result
                    ]
            except Exception as e:
                print(f"Error fetching pinned repos via REST: {e}")
        
        # If still no pinned items, try berrysauce.dev API as another fallback
        if not pinned_nodes:
            print("No pinned repositories found via REST, trying berrysauce.dev API...")
            berrysauce_repos = await fetch_berrysauce_pinned(session, user)
            
            if berrysauce_repos and len(berrysauce_repos) > 0:
                print(f"Found {len(berrysauce_repos)} pinned repositories via berrysauce.dev API")
                
                # Get more details for these repos using GitHub API
                detailed_repos = []
                for berry_repo in berrysauce_repos:
                    repo_owner = berry_repo.get("owner", "")
                    repo_name = berry_repo.get("name", "")
                    if repo_owner and repo_name:
                        try:
                            # Get detailed info from GitHub
                            detail = await s.queries.query_rest(f"/repos/{repo_owner}/{repo_name}")
                            if detail:
                                detailed_repos.append(detail)
                        except Exception as e:
                            print(f"Error fetching details for {repo_owner}/{repo_name}: {e}")
                
                if detailed_repos:
                    # Format the repo data to match the GraphQL format
                    pinned_nodes = [
                        {
                            "name": repo.get("name"),
                            "nameWithOwner": repo.get("full_name"),
                            "description": repo.get("description"),
                            "url": repo.get("html_url"),
                            "stargazerCount": repo.get("stargazers_count", 0),
                            "forkCount": repo.get("forks_count", 0),
                            "primaryLanguage": {
                                "name": repo.get("language"),
                                "color": "#" + format(hash(repo.get("language") or ""), '06x')[0:6]
                            } if repo.get("language") else None,
                            "isPrivate": repo.get("private", False),
                            "updatedAt": repo.get("updated_at")
                        }
                        for repo in detailed_repos
                    ]
        
        # If still no pinned items, try direct web scraping
        if not pinned_nodes:
            print("No pinned repositories found via APIs, trying direct web scraping...")
            scraped_repos = await scrape_pinned_repos(session, user)
            
            if scraped_repos and len(scraped_repos) > 0:
                print(f"Found {len(scraped_repos)} pinned repositories via web scraping")
                
                # Get more details for these repos using GitHub API
                detailed_repos = []
                for scraped_repo in scraped_repos:
                    repo_owner = scraped_repo.get("owner", user)
                    repo_name = scraped_repo.get("name", "")
                    if repo_owner and repo_name:
                        try:
                            # Get detailed info from GitHub
                            detail = await s.queries.query_rest(f"/repos/{repo_owner}/{repo_name}")
                            if detail:
                                # Add scraping-specific info if API is missing it
                                if not detail.get("language") and scraped_repo.get("language"):
                                    detail["language"] = scraped_repo.get("language")
                                    detail["language_color"] = scraped_repo.get("color", "#000000")
                                detailed_repos.append(detail)
                        except Exception as e:
                            print(f"Error fetching details for {repo_owner}/{repo_name}: {e}")
                            
                            # If API fails, create a basic record from scraped data
                            detailed_repos.append({
                                "name": repo_name,
                                "full_name": f"{repo_owner}/{repo_name}",
                                "description": scraped_repo.get("description", ""),
                                "html_url": f"https://github.com/{repo_owner}/{repo_name}",
                                "stargazers_count": 0,
                                "forks_count": 0, 
                                "language": scraped_repo.get("language"),
                                "language_color": scraped_repo.get("color", "#000000"),
                                "private": False,
                                "updated_at": ""
                            })
                
                if detailed_repos:
                    # Format the repo data to match the GraphQL format
                    pinned_nodes = [
                        {
                            "name": repo.get("name"),
                            "nameWithOwner": repo.get("full_name"),
                            "description": repo.get("description"),
                            "url": repo.get("html_url"),
                            "stargazerCount": repo.get("stargazers_count", 0),
                            "forkCount": repo.get("forks_count", 0),
                            "primaryLanguage": {
                                "name": repo.get("language"),
                                "color": repo.get("language_color", "#" + format(hash(repo.get("language") or ""), '06x')[0:6])
                            } if repo.get("language") else None,
                            "isPrivate": repo.get("private", False),
                            "updatedAt": repo.get("updated_at", "")
                        }
                        for repo in detailed_repos
                    ]
        
        # If still no pinned items, use top repos as a last fallback
        if not pinned_nodes:
            print("No pinned repositories found via web scraping, trying top starred repos...")
            # Get all repos from the user
            rest_repo_query = f"/users/{user}/repos?sort=updated&per_page=100"
            all_repos = await s.queries.query_rest(rest_repo_query)
            
            # Sort by stars to get the most popular ones
            if all_repos and isinstance(all_repos, list):
                all_repos.sort(key=lambda x: x.get('stargazers_count', 0), reverse=True)
                # Take the top 6
                top_repos = all_repos[:6]
                print(f"Found {len(top_repos)} top repositories as alternatives")
                
                # Format REST API data to match GraphQL format
                pinned_nodes = [
                    {
                        "name": repo.get("name"),
                        "nameWithOwner": repo.get("full_name"),
                        "description": repo.get("description"),
                        "url": repo.get("html_url"),
                        "stargazerCount": repo.get("stargazers_count", 0),
                        "forkCount": repo.get("forks_count", 0),
                        "primaryLanguage": {
                            "name": repo.get("language"),
                            "color": "#" + format(hash(repo.get("language") or ""), '06x')[0:6]
                        } if repo.get("language") else None,
                        "isPrivate": repo.get("private", False),
                        "updatedAt": repo.get("updated_at")
                    }
                    for repo in top_repos
                ]
        
        # Build stats object
        stats_data = {
            "username": user,
            "name": await s.name,
            "generated_at": datetime.now().isoformat(),
            "stats": {
                "total_stars": await s.stargazers,
                "total_forks": await s.forks,
                "total_contributions": await s.total_contributions,
                "total_repositories": len(await s.repos),
                "total_commits_this_year": additional_stats.get("contributionsCollection", {}).get("totalCommitContributions", 0),
                "total_prs": additional_stats.get("pullRequests", {}).get("totalCount", 0),
                "total_issues": additional_stats.get("issues", {}).get("totalCount", 0),
                "contributed_to_last_year": additional_stats.get("repositoriesContributedTo", {}).get("totalCount", 0),
                "lines_changed": await s.lines_changed,
                "views": await s.views
            },
            "languages": {k: v for k, v in (await s.languages).items()},
            "pinned_repositories": [
                {
                    "name": repo.get("name"),
                    "full_name": repo.get("nameWithOwner"),
                    "description": repo.get("description"),
                    "url": repo.get("url", repo.get("html_url")),
                    "stars": repo.get("stargazerCount", 0),
                    "forks": repo.get("forkCount", 0),
                    "language": {
                        "name": repo.get("primaryLanguage", {}).get("name"),
                        "color": repo.get("primaryLanguage", {}).get("color")
                    } if repo.get("primaryLanguage") else None,
                    "is_private": repo.get("isPrivate", False),
                    "updated_at": repo.get("updatedAt", "")
                }
                for repo in pinned_nodes
            ]
        }
        
        # Ensure output folder exists
        if not os.path.isdir("generated"):
            os.mkdir("generated")
        
        # Write the JSON file
        with open("generated/github_stats.json", "w") as f:
            json.dump(stats_data, f, indent=2)
        
        print(f"GitHub stats JSON exported to generated/github_stats.json")

if __name__ == "__main__":
    asyncio.run(export_stats_json())
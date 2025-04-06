#!/usr/bin/python3

import asyncio
import json
import os
from datetime import datetime, timedelta
import aiohttp

from github_stats import Stats, Queries

async def fetch_additional_stats(queries: Queries) -> dict:
    """Fetch additional GitHub stats not available in the Stats class"""
    # Get current year and last year
    now = datetime.now()
    current_year = now.year
    last_year = current_year - 1
    
    # Define GraphQL query for additional stats
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
    }}
    """
    
    result = await queries.query(query)
    viewer_data = result.get("data", {}).get("viewer", {})
    
    # Add debug output to check pinned items
    pinned_items = viewer_data.get("pinnedItems", {})
    print(f"Pinned items count: {pinned_items.get('totalCount', 0)}")
    
    return viewer_data

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
        
        # Check for pinned items specifically
        pinned_items = additional_stats.get("pinnedItems", {})
        pinned_nodes = pinned_items.get("nodes", [])
        print(f"Pinned items found: {len(pinned_nodes)}")
        
        # Alternative approach to get user repositories if pinned items are empty
        if not pinned_nodes:
            print("No pinned repositories found, trying to get top repositories instead...")
            # Query for user's top repositories
            top_repos_query = """
            {
              viewer {
                repositories(first: 6, orderBy: {field: STARGAZERS, direction: DESC}, privacy: PUBLIC) {
                  nodes {
                    name
                    nameWithOwner
                    description
                    url
                    stargazerCount
                    forkCount
                    primaryLanguage {
                      name
                      color
                    }
                    isPrivate
                    updatedAt
                  }
                }
              }
            }
            """
            top_repos_result = await s.queries.query(top_repos_query)
            top_repos = top_repos_result.get("data", {}).get("viewer", {}).get("repositories", {}).get("nodes", [])
            pinned_nodes = top_repos
            print(f"Found {len(pinned_nodes)} top repositories as alternatives")
        
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
                    "url": repo.get("url"),
                    "stars": repo.get("stargazerCount"),
                    "forks": repo.get("forkCount"),
                    "language": {
                        "name": repo.get("primaryLanguage", {}).get("name"),
                        "color": repo.get("primaryLanguage", {}).get("color")
                    } if repo.get("primaryLanguage") else None,
                    "is_private": repo.get("isPrivate"),
                    "updated_at": repo.get("updatedAt")
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
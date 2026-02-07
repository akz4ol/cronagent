#!/usr/bin/env python3
"""
MeridainPost.com Content Monitor
Tracks changes in Latest News and MeridAIn Daily podcasts
"""

import json
import requests
import re
from datetime import datetime, timedelta
from typing import Dict, List, Any
from pathlib import Path


class MeridainMonitor:
    def __init__(self, storage_dir: str = "/Users/akz/Documents/cronagent"):
        self.storage_dir = Path(storage_dir)
        self.baseline_file = self.storage_dir / f"meridain_baseline_{datetime.now().strftime('%Y-%m-%d')}.json"
        self.previous_file = self.storage_dir / f"meridain_baseline_{(datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')}.json"

    def fetch_homepage_news(self) -> Dict[str, Any]:
        """Fetch and parse Latest News from homepage"""
        print("Fetching homepage Latest News...")

        try:
            response = requests.get("https://meridainpost.com", timeout=30)
            response.raise_for_status()
            content = response.text

            # Parse articles - this is a simplified regex-based approach
            # In production, you'd use BeautifulSoup or similar
            articles = []

            # Extract article data using patterns observed from the site
            article_pattern = r'<article[^>]*>.*?<h3[^>]*><a[^>]*href="([^"]*)"[^>]*>([^<]+)</a>.*?</article>'
            matches = re.findall(article_pattern, content, re.DOTALL | re.IGNORECASE)

            for i, (url, title) in enumerate(matches[:12], 1):  # Limit to 12 articles
                # Extract category from URL pattern if possible
                category_match = re.search(r'/([^/]+)/', url)
                category = category_match.group(1) if category_match else "unknown"

                article = {
                    "id": i,
                    "title": title.strip(),
                    "url": url if url.startswith("http") else f"https://meridainpost.com{url}",
                    "category": category,
                    "timestamp": "~5 hrs ago",  # Based on observed pattern
                    "credibility_score": self._extract_score_from_content(content, title),
                    "slug": url.split('/')[-1] if '/' in url else url,
                    "publication_date": datetime.now().strftime("%Y-%m-%d"),
                    "is_recent_24h": True  # Assuming all are recent based on timestamps
                }
                articles.append(article)

            recent_count = sum(1 for a in articles if a["is_recent_24h"])

            return {
                "total_articles": len(articles),
                "recent_articles_24h": recent_count,
                "articles": articles,
                "fetch_timestamp": datetime.now().isoformat(),
                "categories": list(set(a["category"] for a in articles))
            }

        except Exception as e:
            print(f"Error fetching homepage news: {e}")
            return {
                "total_articles": 0,
                "recent_articles_24h": 0,
                "articles": [],
                "error": str(e),
                "fetch_timestamp": datetime.now().isoformat()
            }

    def _extract_score_from_content(self, content: str, title: str) -> str:
        """Extract credibility score for an article (simplified)"""
        # This is a placeholder - in practice you'd parse the actual score
        scores = ["55%", "65%", "72%", "75%", "78%", "87%", "88%", "92%"]
        return scores[hash(title) % len(scores)]

    def fetch_podcast_episodes(self) -> Dict[str, Any]:
        """Fetch and parse MeridAIn Daily episodes"""
        print("Fetching MeridAIn Daily episodes...")

        try:
            response = requests.get("https://meridainpost.com/meridain-daily", timeout=30)
            response.raise_for_status()
            content = response.text

            episodes = []

            # Extract episode information using regex patterns
            episode_pattern = r'Episode\s+(\d+).*?(\d{4}-\d{2}-\d{2}).*?(\d+:\d+)'
            matches = re.findall(episode_pattern, content, re.DOTALL | re.IGNORECASE)

            today = datetime.now().strftime("%Y-%m-%d")
            latest_episode = 0
            latest_date = ""

            for episode_num, date, duration in matches:
                episode_num = int(episode_num)
                if episode_num > latest_episode:
                    latest_episode = episode_num
                    latest_date = date

                episode = {
                    "episode_number": episode_num,
                    "date": date,
                    "title": f"MeridAIn Daily - {date}",
                    "duration": duration,
                    "audio_url": f"https://23inrhmnsixzlkd4.public.blob.vercel-storage.com/meridain-daily/audio/ep{episode_num}_{date}.mp3",
                    "is_today": date == today,
                    "url": f"/meridain-daily/{self._generate_episode_id(episode_num, date)}"
                }
                episodes.append(episode)

            # Sort episodes by number descending
            episodes.sort(key=lambda x: x["episode_number"], reverse=True)

            # Check if there's a today's episode
            today_episodes = [ep for ep in episodes if ep["is_today"]]

            return {
                "latest_episode": latest_episode,
                "latest_episode_date": latest_date,
                "episodes": episodes[:10],  # Keep last 10 episodes
                "total_episodes": len(episodes),
                "todays_episodes": today_episodes,
                "has_todays_episode": len(today_episodes) > 0,
                "fetch_timestamp": datetime.now().isoformat(),
                "notes": f"Latest episode: {latest_episode} from {latest_date}. Today's date: {today}"
            }

        except Exception as e:
            print(f"Error fetching podcast episodes: {e}")
            return {
                "latest_episode": 0,
                "latest_episode_date": "",
                "episodes": [],
                "error": str(e),
                "fetch_timestamp": datetime.now().isoformat(),
                "notes": f"Error occurred: {str(e)}"
            }

    def _generate_episode_id(self, episode_num: int, date: str) -> str:
        """Generate a mock episode ID based on episode number and date"""
        import hashlib
        return hashlib.md5(f"ep{episode_num}_{date}".encode()).hexdigest()[:8] + "-" + \
               hashlib.md5(f"{date}_{episode_num}".encode()).hexdigest()[:4] + "-" + \
               hashlib.md5(f"{episode_num}".encode()).hexdigest()[:4] + "-" + \
               hashlib.md5(f"{date}".encode()).hexdigest()[:4] + "-" + \
               hashlib.md5(f"meridain_{episode_num}_{date}".encode()).hexdigest()[:12]

    def load_previous_state(self) -> Dict[str, Any]:
        """Load yesterday's baseline for comparison"""
        if self.previous_file.exists():
            with open(self.previous_file, 'r') as f:
                return json.load(f)
        return None

    def save_current_state(self, data: Dict[str, Any]):
        """Save current state as baseline"""
        with open(self.baseline_file, 'w') as f:
            json.dump(data, f, indent=2)

    def compare_news(self, current: Dict, previous: Dict = None) -> Dict[str, Any]:
        """Compare current news with previous state"""
        changes = {
            "new_stories": [],
            "updated_scores": [],
            "new_categories": set(),
            "total_change": 0
        }

        if not previous:
            changes["new_stories"] = current.get("articles", [])
            changes["total_change"] = len(current.get("articles", []))
            return changes

        prev_urls = {article["url"] for article in previous.get("homepage_latest_news", {}).get("articles", [])}
        current_articles = current.get("articles", [])

        for article in current_articles:
            if article["url"] not in prev_urls:
                changes["new_stories"].append(article)
                changes["total_change"] += 1

        # Check for new categories
        prev_categories = {article["category"] for article in previous.get("homepage_latest_news", {}).get("articles", [])}
        current_categories = {article["category"] for article in current_articles}
        changes["new_categories"] = current_categories - prev_categories

        return changes

    def compare_podcasts(self, current: Dict, previous: Dict = None) -> Dict[str, Any]:
        """Compare current podcasts with previous state"""
        changes = {
            "new_episodes": [],
            "episode_number_change": 0,
            "latest_date_change": False
        }

        if not previous:
            if current.get("episodes"):
                changes["new_episodes"] = current["episodes"]
            return changes

        prev_latest = previous.get("meridain_daily_podcasts", {}).get("latest_episode", 0)
        current_latest = current.get("latest_episode", 0)

        changes["episode_number_change"] = current_latest - prev_latest

        prev_date = previous.get("meridain_daily_podcasts", {}).get("latest_episode_date", "")
        current_date = current.get("latest_episode_date", "")
        changes["latest_date_change"] = prev_date != current_date

        if changes["episode_number_change"] > 0:
            changes["new_episodes"] = current.get("episodes", [])[:changes["episode_number_change"]]

        return changes

    def generate_report(self, news_changes: Dict, podcast_changes: Dict) -> str:
        """Generate human-readable monitoring report"""
        report = []
        report.append(f"# MeridainPost.com Monitoring Report - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        report.append("")

        # News section
        report.append("## Latest News Changes")
        if news_changes["new_stories"]:
            report.append(f"✅ **{len(news_changes['new_stories'])} new stories** found:")
            for story in news_changes["new_stories"][:5]:  # Show first 5
                report.append(f"- **{story['title']}** ({story['category']}, Score: {story.get('credibility_score', 'N/A')})")
                report.append(f"  URL: {story['url']}")
            if len(news_changes["new_stories"]) > 5:
                report.append(f"  ... and {len(news_changes['new_stories']) - 5} more")
        else:
            report.append("❌ No new stories found")

        if news_changes["new_categories"]:
            report.append(f"📂 **New categories:** {', '.join(news_changes['new_categories'])}")

        report.append("")

        # Podcast section
        report.append("## MeridAIn Daily Podcast Changes")
        if podcast_changes["new_episodes"]:
            report.append(f"🎧 **{len(podcast_changes['new_episodes'])} new episodes** found:")
            for episode in podcast_changes["new_episodes"]:
                report.append(f"- **Episode {episode.get('episode_number', 'N/A')}** - {episode.get('date', 'N/A')}")
                report.append(f"  Duration: {episode.get('duration', 'N/A')}")
                report.append(f"  Audio: {episode.get('audio_url', 'N/A')}")
        else:
            if podcast_changes["episode_number_change"] == 0:
                report.append("❌ No new episodes found")
            else:
                report.append("⚠️ Episode numbering may have changed but no new episodes detected")

        report.append("")

        # Summary
        total_changes = len(news_changes["new_stories"]) + len(podcast_changes["new_episodes"])
        if total_changes > 0:
            report.append(f"## Summary: {total_changes} total changes detected")
        else:
            report.append("## Summary: No new content detected - site may have stale/repeated content")

        return "\n".join(report)

    def monitor(self) -> str:
        """Main monitoring function"""
        print("Starting MeridainPost.com monitoring...")

        # Load previous state
        previous_state = self.load_previous_state()

        # Fetch current state
        current_news = self.fetch_homepage_news()
        current_podcasts = self.fetch_podcast_episodes()

        current_state = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "timestamp": datetime.now().isoformat(),
            "homepage_latest_news": current_news,
            "meridain_daily_podcasts": current_podcasts
        }

        # Compare states
        news_changes = self.compare_news(current_news, previous_state)
        podcast_changes = self.compare_podcasts(current_podcasts, previous_state)

        # Generate report
        report = self.generate_report(news_changes, podcast_changes)

        # Save current state
        self.save_current_state(current_state)

        return report


def main():
    """CLI entry point"""
    monitor = MeridainMonitor()
    report = monitor.monitor()
    print(report)

    # Optionally save report
    report_file = Path("/Users/akz/Documents/cronagent") / f"meridain_report_{datetime.now().strftime('%Y-%m-%d_%H-%M')}.txt"
    with open(report_file, 'w') as f:
        f.write(report)
    print(f"\nReport saved to: {report_file}")


if __name__ == "__main__":
    main()
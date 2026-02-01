import requests
import time
import os
import json
import re
# Import custom logging
from .utils.logging import get_logger
from typing import Dict, List, Optional, Any, Union

# Configure logging
logger = get_logger(__name__)

class BaseClient:
    """Base client for API interactions with common session handling."""
    def __init__(self, base_url: str, api_key: str = None):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla-Bug-Analyzer/1.0',
            'Accept': 'application/json',
        })

    def _get(self, endpoint: str, params: Dict = None, **kwargs) -> requests.Response:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        return self.session.get(url, params=params, **kwargs)

    def _post(self, endpoint: str, data: Dict = None, **kwargs) -> requests.Response:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        return self.session.post(url, data=data, **kwargs)

class BugzillaClient(BaseClient):
    """Client for Bugzilla REST API."""
    def __init__(self, base_url: str = "https://bugzilla.mozilla.org"):
        super().__init__(base_url)

    def get_bug_data(self, bug_id: int) -> Optional[Dict]:
        logger.info(f"Fetching bug data for Bug {bug_id}...")
        try:
            response = self._get(f"rest/bug/{bug_id}", params={'include_fields': '_all'})
            response.raise_for_status()
            data = response.json()
            if 'bugs' in data and len(data['bugs']) > 0:
                return data['bugs'][0]
        except Exception as e:
            logger.info(f"Error fetching bug data: {e}")
        return None

    def get_bug_comments(self, bug_id: int) -> List[Dict]:
        logger.info(f"Fetching comments for Bug {bug_id}...")
        try:
            response = self._get(f"rest/bug/{bug_id}/comment")
            response.raise_for_status()
            data = response.json()
            if 'bugs' in data and str(bug_id) in data['bugs']:
                return data['bugs'][str(bug_id)]['comments']
        except Exception as e:
            logger.info(f"Error fetching comments: {e}")
        return []

    def get_bug_history(self, bug_id: int) -> List[Dict]:
        logger.info(f"Fetching history for Bug {bug_id}...")
        try:
            response = self._get(f"rest/bug/{bug_id}/history")
            response.raise_for_status()
            data = response.json()
            if 'bugs' in data and len(data['bugs']) > 0:
                return data['bugs'][0].get('history', [])
        except Exception as e:
            logger.info(f"Error fetching history: {e}")
        return []

    def get_bug_attachments(self, bug_id: int) -> List[Dict]:
        logger.info(f"Fetching attachments for Bug {bug_id}...")
        try:
            response = self._get(f"rest/bug/{bug_id}/attachment")
            response.raise_for_status()
            data = response.json()
            if 'bugs' in data and str(bug_id) in data['bugs']:
                return data['bugs'][str(bug_id)]
        except Exception as e:
            logger.info(f"Error fetching attachments: {e}")
    def get_bug_attachments(self, bug_id: int) -> List[Dict]:
        logger.info(f"Fetching attachments for Bug {bug_id}...")
        try:
            response = self._get(f"rest/bug/{bug_id}/attachment")
            response.raise_for_status()
            data = response.json()
            if 'bugs' in data and str(bug_id) in data['bugs']:
                return data['bugs'][str(bug_id)]
        except Exception as e:
            logger.info(f"Error fetching attachments: {e}")
        return []

    def search_bugs(self, query: str, limit: int = 5) -> List[Dict]:
        """Search bugs using quicksearch."""
        logger.info(f"Searching Bugzilla for: {query[:50]}...")
        try:
            params = {
                'quicksearch': query,
                'limit': limit,
                'include_fields': 'id,summary,status'
            }
            response = self._get("rest/bug", params=params)
            response.raise_for_status()
            data = response.json()
            return data.get('bugs', [])
        except Exception as e:
            logger.info(f"Error searching bugs: {e}")
            return []

class PhabricatorClient(BaseClient):
    """Client for Phabricator Conduit API."""
    def __init__(self, base_url: str = "https://phabricator.services.mozilla.com", token: str = None):
        super().__init__(base_url, token)
        super().__init__(base_url, token)
        self.token = os.environ.get('PHABRICATOR_TOKEN', 'api-mu2nb5jwbnkuk56vofuwee2rr3e5')

    def _conduit_call(self, method: str, params: Dict = None) -> Optional[Any]:
        if params is None:
            params = {}
        
        # Conduit expects params as a JSON string in 'params' form field, 
        # plus the token in the params inside that JSON or as a separate __conduit__ field.
        # But simpler way for most clients is passing token in the params structure.
        
        if self.token:
            params['__conduit__'] = {'token': self.token}
            
        data = {
            'params': json.dumps(params),
            'output': 'json'
        }
        
        try:
            response = self._post(f"api/{method}", data=data)
            response.raise_for_status()
            result = response.json()
            if result.get('error_code') is not None:
                # Some public endpoints might work without token, but often return error if specific data requested
                # If we get an error and have no token, user might need one.
                logger.info(f"Phabricator API Error: {result.get('error_info')}")
                return None
            return result.get('result')
        except Exception as e:
            logger.info(f"Error calling Phabricator API {method}: {e}")
            return None

    def search_revisions_by_bug_id(self, bug_id: int) -> List[Dict]:
        """
        Search for revisions linked to a bug ID. 
        """
        logger.info(f"Searching Phabricator for revisions related to Bug {bug_id}...")
        
        found_revs = []
        
        # We can use differential.revision.search
        # Using 'query' constraint is one way, but sometimes 'bugs' constraint (if custom field exists) works better.
        # However, standard Conduit often relies on text search.
        
        params = {
            'constraints': {
                'query': str(bug_id)
            },
            'limit': 10
        }
        
        result = self._conduit_call('differential.revision.search', params)
        if result and 'data' in result:
            for item in result['data']:
                fields = item.get('fields', {})
                title = fields.get('title', '')
                summary = fields.get('summary', '')
                
                # Check if bug ID is in title or summary
                if str(bug_id) in title or str(bug_id) in summary:
                    found_revs.append(item)
                    
        return found_revs

    def get_revision_diff(self, revision_id: int) -> Optional[str]:
        """Get the raw diff for a revision using Conduit API."""
        try:
             # First, we need the diffID.
             # We can search for the revision to get its latest diffID.
             params = {'constraints': {'ids': [int(revision_id)]}}
             result = self._conduit_call('differential.revision.search', params)
             
             diff_id = None
             if result and 'data' in result and result['data']:
                 diff_id = result['data'][0]['fields'].get('diffID')
             
             if not diff_id:
                 logger.info(f"No diffID found for revision {revision_id}")
                 return None
                 
             # Now fetch raw diff
             # differential.getrawdiff needs diffID
             raw_diff = self._conduit_call('differential.getrawdiff', {'diffID': diff_id})
             return raw_diff

        except Exception as e:
            logger.info(f"Error fetching raw diff: {e}")
            return None

class CrashStatsClient(BaseClient):
    """Client for Mozilla Crash Stats API."""
    def __init__(self, base_url: str = "https://crash-stats.mozilla.org"):
        super().__init__(base_url)

    def search_crashes_by_bug(self, bug_id: int, limit: int = 10) -> List[Dict]:
        """Search for crashes linked to a bug ID."""
        logger.info(f"Searching Crash Stats for Bug {bug_id}...")
        try:
            # SuperSearch API
            # We search where 'bug_id' (or similar field) matches our ID.
            # Field is likely 'bug_ids'.
            params = {
                'bug_id': bug_id,
                '_results_number': limit,
                '_columns': ['uuid', 'date', 'product', 'version', 'signature']
            }
            response = self._get("api/SuperSearch/", params=params)
            response.raise_for_status()
            data = response.json()
            return data.get('hits', [])
        except Exception as e:
            logger.info(f"Error fetching crash stats: {e}")
            return []



class TreeherderClient(BaseClient):
    """Client for Treeherder API."""
    def __init__(self, base_url: str = "https://treeherder.mozilla.org"):
        super().__init__(base_url)

    def get_push_health(self, revision: str, repo: str = "mozilla-central") -> Optional[Dict]:
        """Get build/test health for a specific revision (commit hash)."""
        logger.info(f"Checking Treeherder for revision {revision}...")
        try:
            response = self._get(f"api/project/{repo}/push/", params={'revision': revision})
            response.raise_for_status()
            data = response.json()
            results = data.get('results', [])
            
            if not results:
                return None
                
            return results[0]
            
        except Exception as e:
            logger.info(f"Error fetching treeherder data: {e}")
            return None

class MercurialClient(BaseClient):
    """Client for hg.mozilla.org."""
    def __init__(self, base_url: str = "https://hg.mozilla.org"):
        super().__init__(base_url)

    def get_commit(self, repo: str, commit_hash: str) -> Optional[Dict]:
        url = f"{self.base_url}/{repo}/json-rev/{commit_hash}"
        try:
            response = requests.get(url)
            response.raise_for_status()
            return response.json()
        except:
            return None

    def get_file_tree(self, repo: str, revision: str = "tip", path: str = "") -> List[str]:
        """
        Get the file tree (manifest) for a given revision and path.
        Returns a list of file paths.
        """
        # Fix: The 404 might be because hg.mozilla.org structure or path needs trailing slash handling
        # or because json-manifest expects 'raw-file' style paths
        # path should NOT have leading slash
        path = path.lstrip('/')
        if path and not path.endswith('/'):
            path += '/'
            
        # Try both with and without tailing slash for directory
        url = f"{self.base_url}/{repo}/json-manifest/{revision}/{path}"
        try:
            response = requests.get(url)
            # If 404, maybe it's not a directory but a file?
            if response.status_code == 404:
                 logger.info(f"Path {path} not found as dir, checking if parent exists...")
                 return []
                 
            response.raise_for_status()
            data = response.json()
            
            files = []
            if 'dirs' in data:
                for d in data['dirs']:
                    files.append(f"{d['basename']}/")
            if 'files' in data:
                for f in data['files']:
                    files.append(f['basename'])
            return files
        except Exception as e:
            logger.info(f"Error fetching file tree for {repo}/{path}: {e}")
            return []

    def get_file_content(self, repo: str, file_path: str, revision: str = "tip") -> Optional[str]:
        """Get raw content of a file."""
        url = f"{self.base_url}/{repo}/raw-file/{revision}/{file_path}"
        try:
            response = requests.get(url)
            response.raise_for_status()
            return response.text
        except Exception as e:
            logger.info(f"Error fetching file content {file_path}: {e}")
            return None

class SearchfoxClient(BaseClient):
    """Client for Searchfox."""
    def __init__(self, base_url: str = "https://searchfox.org"):
        super().__init__(base_url)

    def search(self, query: str, repo: str = "mozilla-central") -> Optional[Dict]:
        url = f"{self.base_url}/{repo}/search"
        try:
            # Searchfox returns HTML. We need to parse it or use the 'format=json' if available (it's not usually public).
            # Actually, let's try to scrape the result using regex or simple string manipulation 
            # since adding BeautifulSoup might be heavy or not in requirements.
            response = requests.get(url, params={'q': query})
            response.raise_for_status()
            
            content = response.text
            
            # Simple heuristic regex to find search results in the HTML
            # Results look like: <a href="/mozilla-central/source/path/to/file#123">
            # We want to extract path and maybe context.
            
            # This is very brittle, but public API is not available.
            hits = []
            # Regex to find links to source files in search results
            # Typical result link: <a href="/mozilla-central/source/path/to/file.cpp#123">
            # We look for hrefs starting with /{repo}/source/
            pattern = re.compile(f'href="/{repo}/source/([^"]+)"')
            matches = pattern.findall(content)
            
            # Deduplicate and format
            seen = set()
            for m in matches:
                # m might include line number "foo.cpp#123"
                if m not in seen:
                    seen.add(m)
                    hits.append({'path': m})
            
            # Mimic the structure expected by advanced_tools
            return {'normal': hits}
            
        except Exception as e:
            logger.info(f"Error searching Searchfox: {e}")
            return None

    def get_content(self, file_path: str, repo: str = "mozilla-central") -> Optional[str]:
        url = f"{self.base_url}/{repo}/source/{file_path}"
        try:
            response = requests.get(url)
            response.raise_for_status()
            return response.text
        except:
            return None

class GitHubClient(BaseClient):
    """Client for GitHub API (mozilla/gecko-dev)."""
    def __init__(self, base_url: str = "https://api.github.com"):
        super().__init__(base_url)
        self.raw_url = "https://raw.githubusercontent.com/mozilla/gecko-dev/master"

    def get_tree(self, path: str) -> List[str]:
        """List files in a directory using GitHub API."""
        path = path.strip('/')
        url = f"repos/mozilla/gecko-dev/contents/{path}"
        logger.info(f"GitHub: fetching tree for {path}")
        try:
            response = self._get(url)
            # 404 means path doesn't exist or is not a dir (or is a file)
            if response.status_code == 404:
                return []
            response.raise_for_status()
            
            data = response.json()
            files = []
            if isinstance(data, list):
                for item in data:
                    if item['type'] == 'file':
                        files.append(item['name'])
                    elif item['type'] == 'dir':
                        files.append(f"{item['name']}/")
            return files
        except Exception as e:
            logger.info(f"Error fetching GitHub tree for {path}: {e}")
            return []

    def get_file_content(self, path: str) -> Optional[str]:
        """Fetch raw file content from GitHub."""
        path = path.strip('/')
        url = f"{self.raw_url}/{path}"
        try:
            response = requests.get(url)
            if response.status_code == 404:
                 return None
            response.raise_for_status()
            return response.text
        except Exception as e:
            logger.info(f"Error fetching GitHub file {path}: {e}")
            return None

    def search_code(self, query: str, repo: str = "mozilla/gecko-dev") -> List[Dict]:
        """
        Search for code in the repository.
        Returns a list of dicts with 'path' and 'context' (if available).
        """
        url = f"search/code"
        params = {
            'q': f"{query} repo:{repo}",
            'per_page': 10
        }
        try:
            # Note: GitHub Search API has strict rate limits.
            response = self._get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            items = data.get('items', [])
            results = []
            for item in items:
                results.append({
                    'path': item.get('path'),
                    'url': item.get('html_url')
                })
            return results
        except Exception as e:
            logger.info(f"Error searching GitHub: {e}")
            return []

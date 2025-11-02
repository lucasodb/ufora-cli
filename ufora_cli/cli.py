#!/usr/bin/env python3
"""
Ufora CLI - A command-line tool for accessing UGent course materials from Ufora
"""

import json
import pickle
import re
from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin

import click
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt
from rich.progress import Progress

console = Console()

# Configuration
CONFIG_DIR = Path.home() / ".config" / "ufora-cli"
COOKIES_FILE = CONFIG_DIR / "cookies.pkl"
CONFIG_FILE = CONFIG_DIR / "config.json"
BASE_URL = "https://ufora.ugent.be"
LOGIN_URL = "https://elosp.ugent.be/welcome/uforalogin?"
LOGGED_IN_URL = "https://ufora.ugent.be/d2l/home"

CONFIG_DIR.mkdir(parents=True, exist_ok=True)


class UforaSession:
    """Manages authentication and requests to Ufora"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'nl-BE,nl;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        })
    
    def load_cookies(self):
        """Load cookies from file"""
        if COOKIES_FILE.exists():
            with open(COOKIES_FILE, 'rb') as f:
                cookies = pickle.load(f)
                self.session.cookies.update(cookies)
            return True
        return False
    
    def save_cookies(self):
        """Save cookies to file"""
        with open(COOKIES_FILE, 'wb') as f:
            pickle.dump(self.session.cookies, f)
    
    def is_authenticated(self):
        """Check if current session is authenticated"""
        try:
            response = self.session.get(BASE_URL, timeout=10)
            # If we're redirected to login, we're not authenticated
            return 'elosp.ugent.be' not in response.url
        except Exception as e:
            console.print(f"[red]Error checking authentication: {e}[/red]")
            return False
    
    def login_with_browser(self):
        """Login via headless browser and extract 2FA code"""
        console.print("[yellow]Logging in...[/yellow]")

        config = load_config()
        set_email = config.get('email', '')
        twofa_method = config.get('2fa_method', 'app')  # Default to 'app' if not set

        email = Prompt.ask("\n[cyan]Enter your UGent email[/cyan]", default=set_email)
        password = Prompt.ask("[cyan]Enter your password[/cyan]", password=True)

        with sync_playwright() as p:
            browser = p.firefox.launch(headless=True)
            context = browser.new_context(
                locale='en-US',
                extra_http_headers={
                    'Accept-Language': 'en-US,en;q=0.9'
                }
            )
            page = context.new_page()
            
            console.print("\n[yellow]Inserting login information...[/yellow]")

            try:
                page.goto(LOGIN_URL)
                
                # Fill in email
                page.fill('input[placeholder="Email"]', email)
                page.locator('text=Next').click()

                # Fill in password
                page.fill('input[placeholder="Password"]', password)
                page.locator('text=Sign in').click()
                
                page.wait_for_timeout(2000)
            
                # Handle 2FA based on configured method
                if twofa_method == 'app':
                    # Try to extract 2FA code from the page
                    console.print("[yellow]Finding 2FA code...[/yellow]")
                    try:
                        all_divs = page.query_selector_all('div')
                        for div in all_divs:
                            text = (div.text_content() or '').strip()
                            if text.isdigit() and len(text) == 2:
                                console.print(f"\n[green]2FA Code: {text}[/green]")
                                console.print("[yellow]Enter this code on your device to complete authentication[/yellow]\n")
                                break
                    except:
                        pass
                else:  # sms
                    # Select Text
                    page.locator('text=Text').click()

                    console.print("[yellow]2FA code will be sent via SMS[/yellow]")
                    
                    # Prompt user for the SMS code
                    sms_code = Prompt.ask("\n[cyan]Enter the 2FA code from SMS[/cyan]")
                    
                    # Find the input field for the 2FA code and enter it
                    try:
                        # Look for the verification code input field
                        code_input = page.locator('input[name="otc"]').or_(page.locator('input[type="tel"]'))
                        code_input.fill(sms_code)
                        
                        # Click verify/submit button
                        page.locator('text=Verify').or_(page.locator('input[type="submit"]')).click()
                        
                        console.print("[green]✓ 2FA code submitted[/green]")
                    except Exception as e:
                        console.print(f"[red]Error entering 2FA code: {e}[/red]")
                        console.print("[yellow]You may need to manually complete the 2FA step[/yellow]")
                
                # Wait for successful login (redirect away from auth page)
                console.print("[yellow]Waiting for authentication to complete...[/yellow]")
                page.wait_for_url(LOGGED_IN_URL, timeout=120000)
                    
                # Extract cookies
                cookies = context.cookies()
                browser.close()
                
                # Convert to requests format
                for cookie in cookies:

                    expires = None
                    if 'expires' in cookie and cookie['expires'] != -1:
                        expires = int(cookie['expires'])

                    self.session.cookies.set(
                        cookie['name'],
                        cookie['value'],
                        domain=cookie.get('domain', ''),
                        path=cookie.get('path', '/'),
                        secure=cookie.get('secure', False),
                        expires=expires
                    )
                
                self.save_cookies()
                console.print("[green]✓ Login successful! Cookies saved.[/green]")
                
            except Exception as e:
                console.print(f"[red]✗ Login failed: {e}[/red]")
                browser.close()
    
    def refresh_session_with_persistent_cookies(self):
        """Try to get new session cookies using persistent Microsoft cookies"""
        try:
            console.print("[yellow]Refreshing with saved credentials...[/yellow]")
            
            from playwright.sync_api import sync_playwright
            
            with sync_playwright() as p:
                browser = p.firefox.launch(headless=True)
                
                # Create context with our existing cookies
                context = browser.new_context(
                    locale='en-US',
                    extra_http_headers={
                        'Accept-Language': 'en-US,en;q=0.9'
                    }
                )
                
                # Add all our cookies to the browser context
                playwright_cookies = []
                for cookie in self.session.cookies:
                    playwright_cookie = {
                        'name': cookie.name,
                        'value': cookie.value,
                        'domain': cookie.domain,
                        'path': cookie.path,
                    }
                    if cookie.expires:
                        playwright_cookie['expires'] = cookie.expires
                    if cookie.secure:
                        playwright_cookie['secure'] = True
                        
                    playwright_cookies.append(playwright_cookie)
                
                context.add_cookies(playwright_cookies)
                
                page = context.new_page()
                
                # Navigate to Ufora - should get to welcome page
                page.goto(BASE_URL, timeout=30000)
                page.wait_for_timeout(2000)
                
                # If we're at the welcome page, click the Ufora login button
                if 'elosp.ugent.be/welcome' in page.url:
                    console.print("[yellow]At welcome page, clicking Ufora login...[/yellow]")
                    try:
                        # Click the Ufora login button
                        page.locator('text=Ufora login').click()
                        
                        # Wait a bit for redirect
                        page.wait_for_timeout(3000)
                        
                        # Check if we're at Microsoft account picker
                        if 'login.microsoftonline.com' in page.url and 'select_account' in page.url:
                            console.print("[yellow]At account picker, selecting account...[/yellow]")
                            try:
                                # Click on the first account (your signed-in account)
                                account = page.locator('div.table-row').filter(has_text='Signed in').first
                                account.click()

                                # Wait for navigation to complete
                                page.wait_for_url('**/d2l/home**', timeout=20000)
                            except Exception as e:
                                console.print(f"Could not select account: {e}")
                                # Try alternative selector
                                try:
                                    page.locator('div[role="button"]:has-text("Signed in")').click()
                                    page.wait_for_url('**/d2l/home**', timeout=30000)
                                except:
                                    pass
                        else:
                            # Not at account picker, maybe already navigated through
                            page.wait_for_url('**/d2l/home**', timeout=30000)
                        
                    except Exception as e:
                        console.print(f"Navigation error: {e}")
                
                final_url = page.url
                
                # Check if we're authenticated
                if 'ufora.ugent.be' in final_url and 'elosp' not in final_url:
                    # Extract new cookies
                    new_cookies = context.cookies()
                    
                    # Update session with new cookies
                    for cookie in new_cookies:
                        expires = None
                        if 'expires' in cookie and cookie['expires'] != -1:
                            expires = int(cookie['expires'])
                        
                        self.session.cookies.set(
                            cookie['name'],
                            cookie['value'],
                            domain=cookie.get('domain', ''),
                            path=cookie.get('path', '/'),
                            secure=cookie.get('secure', False),
                            expires=expires
                        )
                    
                    browser.close()
                    self.save_cookies()
                    console.print("[green]✓ Session refreshed successfully![/green]")
                    return True
                
                browser.close()
                console.print(f"[yellow]Could not refresh ...[/yellow]")
                return False
                
        except Exception as e:
            console.print(f"[yellow]Session refresh failed: {e}[/yellow]")
            return False

    def ensure_authenticated(self):
        """Ensure we have a valid authenticated session"""
        if self.load_cookies():
            if self.is_authenticated():
                return
            else:
                console.print("[yellow]Session expired...[/yellow]")
                # Try to refresh using persistent cookies first
                if self.refresh_session_with_persistent_cookies():
                    return
                console.print("[yellow]Need to re-login with password/2FA[/yellow]")
        
        self.login_with_browser()
    
    def get(self, url, **kwargs):
        """Make authenticated GET request"""
        return self.session.get(url, **kwargs)


class UforaCourses:
    """Handles course listing and materials"""
    
    def __init__(self, session: UforaSession):
        self.session = session
    
    def get_courses(self):
        """Fetch list of courses using the Brightspace API with pagination"""
        try:
            # Use the D2L/Brightspace API to get enrollments
            api_versions = ['1.28', '1.9', '1.8', '1.4', '1.0']
            
            courses = []
            response = None
            api_url = None
            
            # Try different API versions
            for version in api_versions:
                api_url = f"{BASE_URL}/d2l/api/lp/{version}/enrollments/myenrollments/"
                response = self.session.get(api_url)
                if response.status_code == 200:
                    break
            
            if not response or response.status_code != 200:
                console.print(f"[red]API returned status code: {response.status_code if response else 'No response'}[/red]")
                return []
            
            # Loop to handle pagination with Bookmark
            while response:
                enrollments = response.json()
                
                for enrollment in enrollments.get('Items', []):
                    org_unit = enrollment.get('OrgUnit', {})
                    access = enrollment.get('Access', {})
                    
                    # Only include course offerings (Type 3) that are active
                    if org_unit.get('Type', {}).get('Id') == 3 and access.get('IsActive'):
                        course_id = str(org_unit.get('Id', ''))
                        course_name = org_unit.get('Name', '')
                        course_code = org_unit.get('Code', '')
                        start_date = access.get('StartDate', '')

                        if " - " in course_name:
                            course_name = course_name.split(" - ", 1)[1]

                        if course_code and course_code != course_name:
                            title = f"{course_code} - {course_name}"
                        else:
                            title = course_name
                        
                        courses.append({
                            'title': title,
                            'url': f"{BASE_URL}/d2l/home/{course_id}",
                            'content_url': f"{BASE_URL}/d2l/le/content/{course_id}/Home",
                            'id': course_id,
                            'code': course_code,
                            'name': course_name,
                            'start': start_date
                        })
                
                # Check if there is a Bookmark for the next page
                if enrollments.get('PagingInfo', {}).get('HasMoreItems', False):
                    bookmark = enrollments.get('PagingInfo', {}).get('Bookmark', None)
                    if bookmark:
                        # Add the Bookmark to the request to fetch the next page
                        next_url = f"{api_url}?Bookmark={bookmark}"
                        response = self.session.get(next_url)
                    else:
                        # No more Bookmark, stop paginating
                        response = None
                else:
                    # No more items, stop paginating
                    response = None

            return courses
            
        except Exception as e:
            console.print(f"[red]Error fetching courses: {e}[/red]")
            import traceback
            traceback.print_exc()
            return []
    
    def _extract_materials_from_page(self, module_list):
        """
        Helper method to extract materials from the current page HTML.
        Returns a list of material dictionaries with title, url, type, and id.
        """
        materials = []
        file_items = module_list.find_all('li', class_='d2l-datalist-item')
        
        for file_item in file_items:
            link = file_item.find('a', class_='d2l-link', href=re.compile(r'/d2l/le/content/'))
            if link:
                title = link.get_text(strip=True)
                url = link.get('href', '')
                
                # Extract content ID from URL
                file_id_match = re.search(r'/viewContent/(\d+)/View', url)
                file_id = file_id_match.group(1) if file_id_match else None
                
                # Get file type
                file_type_elem = file_item.find('div', class_='d2l-textblock d2l-body-small')
                file_type = file_type_elem.get_text(strip=True) if file_type_elem else 'Unknown'
                
                if url:
                    materials.append({
                        'title': title,
                        'url': urljoin(BASE_URL, url),
                        'type': file_type,
                        'id': file_id
                    })
        
        return materials

    # (Only one level of nested module is supported at this moment)
    def get_course_content(self, content_url):
        """Get all content/materials for a course, grouped by modules (including nested)"""
        try:
            # Fetch the main course content page
            response = self.session.get(content_url)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            modules = {}
            
            # Get root-level modules and their files
            table_of_contents = soup.find('ul', class_='d2l-datalist vui-list')
            
            if not table_of_contents:
                console.print("[red]Table of contents not found on the course page[/red]")
                return []
            
            # Find root-level module items
            module_lists = table_of_contents.find_all('li', class_='d2l-datalist-item d2l-datalist-newitem d2l-datalist-item-hide-separators d2l-datalist-simpleitem')
            
            if not module_lists:
                console.print("[red]Modules not found in the table of contents[/red]")
                return []
            
            # Process each root-level module
            for module_list in module_lists:
                module_header = module_list.find('h2')
                if not module_header:
                    continue
                
                module_name = module_header.get_text(strip=True)
                if not module_name:
                    continue
                
                # Extract materials from this module on the current page
                materials = self._extract_materials_from_page(module_list)
                
                if materials:
                    modules[module_name] = {
                        'name': module_name,
                        'materials': materials,
                        'subfolders': []
                    }

            # Find and process nested modules (subfolders)
            nested_modules = soup.find_all(
                'li',
                class_='d2l-le-TreeAccordionItem',
                id=lambda x: x and x.startswith('D2L_LE_Content_TreeBrowser_D2L.LE.Content.ContentObject.ModuleCO-')
            )
            
            # Filter to only non-root items (items that are nested)
            filtered_nested = [item for item in nested_modules if 'd2l-le-TreeAccordionItem-Root' not in item.get('class', [])]
            
            # Process each nested module
            for nested_item in filtered_nested:
                # Find parent module name
                parent = nested_item.find_parent('li', class_='d2l-le-TreeAccordionItem d2l-le-TreeAccordionItem-Root')
                if not parent:
                    continue
                
                parent_header = parent.find('div', class_='d2l-textblock')
                parent_name = parent_header.get_text(strip=True) if parent_header else None
                if not parent_name:
                    continue
                
                # Get subfolder name and ID
                folder_header = nested_item.find('div', class_='d2l-textblock')
                folder_name = folder_header.get_text(strip=True) if folder_header else None
                if not folder_name or 'module:' in folder_name.lower():
                    continue
                
                folder_id_match = re.search(r'D2L_LE_Content_TreeBrowser_D2L\.LE\.Content\.ContentObject\.ModuleCO-(\d+)', nested_item['id'])
                folder_id = folder_id_match.group(1) if folder_id_match else None
                if not folder_id:
                    continue
                
                # Make request to navigate to this submodule
                try:
                    modified_url = content_url.rstrip('Home') + 'ModuleDetailsPartial'
                    params = {
                        'mId': folder_id,
                        'writeHistoryEntry': '0',
                        '_d2l_prc$headingLevel': '2',
                        '_d2l_prc$scope': '',
                        '_d2l_prc$hasActiveForm': 'false',
                        'isXhr': 'true',
                    }
                    
                    response = self.session.get(modified_url, params=params)
                    
                    # Parse the response to get submodule contents
                    response = self.session.get(content_url)
                    soup = BeautifulSoup(response.text, 'html.parser')
                    
                    # Extract materials from this submodule
                    subfolder_materials = self._extract_materials_from_page(soup)
                    
                    # Create the subfolder entry
                    subfolder = {
                        'name': folder_name,
                        'materials': subfolder_materials
                    }
                    
                    # Add to parent module's subfolders
                    if parent_name in modules:
                        modules[parent_name]['subfolders'].append(subfolder)
                    else:
                        # If parent doesn't exist yet, create it
                        modules[parent_name] = {
                            'name': parent_name,
                            'materials': [],
                            'subfolders': [subfolder]
                        }
                        
                except Exception as e:
                    console.print(f"[yellow]Warning: Could not fetch contents for subfolder '{folder_name}': {e}[/yellow]")
                    continue
            
            # Convert dict to list and format for output
            modules_list = []
            for module_data in modules.values():
                module_entry = {
                    'name': module_data['name'],
                    'materials': module_data['materials']
                }
                
                # Add subfolders if they exist
                if module_data['subfolders']:
                    module_entry['subfolders'] = module_data['subfolders']
                
                modules_list.append(module_entry)

            return modules_list
            
        except Exception as e:
            console.print(f"[red]Error fetching course content: {e}[/red]")
            import traceback
            traceback.print_exc()
            return []


    def download_file(self, course_id, file_id, dest_path):
        """Download a file to the specified path"""
        url = f"{BASE_URL}/d2l/le/content/{course_id}/topics/files/download/{file_id}/DirectFileTopicDownload"
        
        try:
            response = self.session.get(url, stream=True)
            response.raise_for_status()
            
            with open(dest_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            return True
        except Exception as e:
            console.print(f"[red]Error downloading file: {e}[/red]")
            return False

# The course content page state needs to be set to have the Table of Contents
# as the active selected module, since we otherwise can't access the overview of all modules and submodules
def set_table_of_contents_state(session, content_url):
    """Simulate clicking on the Table of Contents tab to set the state."""
    try:
        # Endpoint for setting the state to Table of Contents
        modified_url = content_url.rstrip('Home') + 'PartialMainView'
        
        # Parameters to set the state to Table of Contents
        params = {
            'identifier': 'TOC',
            'moduleTitle': 'Table of Contents',
            '_d2l_prc$headingLevel': '2',
            '_d2l_prc$scope': '',
            '_d2l_prc$hasActiveForm': 'false',
            'isXhr': 'true',
        }
        
        # Send a GET or POST request depending on the site's behavior
        response = session.get(modified_url, params=params)
        
        # If the request was successful, the state should be set to the Table of Contents
        if response.status_code == 200:
            return True
        else:
            console.print(f"[red]Failed to set state: {response.status_code}[/red]")
            return False

    except Exception as e:
        console.print(f"[red]Error setting state: {e}[/red]")
        return False

def load_config():
    """Load configuration (e.g., base directory for courses)"""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}


def save_config(config):
    """Save configuration"""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)


@click.group()
def cli():
    """Ufora CLI - Download your UGent course material from the command line"""
    pass


@cli.command()
def login():
    """Login to Ufora (opens browser for authentication)"""
    session = UforaSession()
    session.login_with_browser()


@cli.command()
def courses():
    """List all your courses that started this year"""
    session = UforaSession()
    session.ensure_authenticated()
    
    ufora = UforaCourses(session)
    course_list = ufora.get_courses()
    
    if not course_list:
        console.print("[yellow]No courses found. You may need to adjust the scraping selectors.[/yellow]")
        return
    
    current_year = datetime.now().year
    
    # Filter courses to include only those starting in the current year
    filtered_courses = []
    for course in course_list:
        start_date = course.get('start')
        if start_date:
            # Parse the start date (assuming it's in ISO 8601 format)
            try:
                start_datetime = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
                if start_datetime.year == current_year:
                    filtered_courses.append(course)
            except ValueError:
                # If the date is not in a valid format, skip it
                continue
    
    if not filtered_courses:
        console.print(f"[yellow]No courses started in {current_year} found.[/yellow]")
        return
    
    # Display the filtered courses
    table = Table(title=f"Your Courses Started in {current_year}", header_style="bold green")
    table.add_column("ID", style="bold cyan")
    table.add_column("Course Name")
    
    for idx, course in enumerate(filtered_courses, 1):
        table.add_row(str(idx), course['title'])
    
    console.print()
    console.print(table)
    console.print()
    
    # Save the filtered course list for later reference
    config = load_config()
    config['courses'] = filtered_courses
    save_config(config)


@cli.command()
@click.argument('course_id', type=int)
def materials(course_id):
    """List materials for a specific course (by ID from 'courses' command), including subfolders (in one table)"""
    config = load_config()
    courses = config.get('courses', [])
    
    if course_id < 1 or course_id > len(courses):
        console.print("[red]Invalid course ID[/red]")
        return
    
    course = courses[course_id - 1]
    
    session = UforaSession()
    session.ensure_authenticated()
    
    ufora = UforaCourses(session)
    url = course['content_url']

    if not set_table_of_contents_state(session, url):
        return []

    modules = ufora.get_course_content(url)
    
    if not modules:
        console.print("[yellow]No materials found or unable to parse content.[/yellow]")
        return

    # Collect all rows recursively with indentation
    rows = []

    def collect_rows(module, indent=0):
        indent_str = " " * (indent * 2)
        # Add a visual section header for the module
        rows.append((f"{indent_str}[bold cyan]{module['name']}[/bold cyan]", ""))
        # Add materials
        for material in module.get("materials", []):
            title = f"{indent_str} [link={material['url']}]{material['title']}[/link]"
            type_str = material.get("type", "Unknown")
            rows.append((title, type_str))
        # Add subfolders recursively
        for sub in module.get("subfolders", []):
            collect_rows(sub, indent + 1)

    for module in modules:
        collect_rows(module)

    # Create a single table
    table = Table(title=f"Course materials for {course['name']}", header_style="bold green")
    table.add_column("Title", overflow="fold")
    table.add_column("Type", style="cyan")

    for title, type_str in rows:
        table.add_row(title, type_str)
    
    console.print()
    console.print(table)
    console.print()


def download_materials(ufora, course_id, materials, base_dir, progress_task=None, progress_obj=None):
    """Helper function to download materials to a directory"""
    downloaded = 0
    failed = 0
        
    for item in materials:
        filename = item['title']
        # Sanitize filename
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        dest_path = base_dir / filename
        
        # Don't try to download undownloadable content
        if item['type'] in ['Assignment', 'Discussion Topic']:
            if progress_obj and progress_task is not None:
                progress_obj.advance(progress_task)
            continue
        
        if ufora.download_file(course_id, item['id'], dest_path):
            console.print(f" [green]✓ Saved to {dest_path}[/green]")
            downloaded += 1
        else:
            console.print(f" [red]✗ Failed to download {filename}[/red]")
            failed += 1
        
        if progress_obj and progress_task is not None:
            progress_obj.advance(progress_task)
    
    return downloaded, failed


@cli.command()
@click.argument('course_id', type=int)
@click.option('--dir', '-d', default=None, help='Target directory (relative or absolute path)')
@click.option('--base', '-b', is_flag=True, help='Download to configured base directory')
def download(course_id, dir, base):
    """Download course materials"""
    config = load_config()
    courses = config.get('courses', [])
    
    if course_id < 1 or course_id > len(courses):
        console.print("[red]Invalid course ID[/red]")
        return
    
    course = courses[course_id - 1]
    
    # Determine target directory
    if dir:
        # Explicit directory specified
        target_dir = Path(dir).expanduser().resolve()
    elif base:
        # Use saved/configured base directory
        base_dir = config.get('base_directory', str(Path.home() / 'uni'))
        target_dir = Path(base_dir) / course['name']
    else:
        # Default: current working directory
        target_dir = Path.cwd()
    
    target_dir.mkdir(parents=True, exist_ok=True)
    
    session = UforaSession()
    session.ensure_authenticated()
    
    ufora = UforaCourses(session)
    url = course['content_url']

    if not set_table_of_contents_state(session, url):
        return []

    materials = ufora.get_course_content(url)
    
    if not materials:
        console.print("[yellow]No materials found[/yellow]")
        return
    
    # Display modules to the user
    table = Table(title=f"Available Modules for \n {course['name']}", header_style="bold green")
    table.add_column("ID", justify="right", style="bold cyan")
    table.add_column("Module Name")

    for idx, module in enumerate(materials, start=1):
        table.add_row(str(idx), module['name'])
    
    console.print()
    console.print(table)
    console.print()

    # Prompt user to select a module
    while True:
        try:
            module_idx = int(Prompt.ask("Enter the module ID to select"))
            if module_idx < 1 or module_idx > len(materials):
                raise ValueError("Invalid module ID.")
            break
        except ValueError as e:
            console.print(f"[red]Please enter a valid number from the list.[/red]")

    selected_module = materials[module_idx - 1]

    # Display files/submodules for the selected module
    table = Table(title=f"Available Files in {selected_module['name']}", header_style="bold green")
    table.add_column("ID", justify="right", style="bold cyan")
    table.add_column("File Name")
    table.add_column("Type", style="cyan")
    
    for idx, material in enumerate(selected_module['materials'], start=1):
        table.add_row(str(idx), material['title'], material['type'])

    if 'subfolders' in selected_module and selected_module['subfolders']:
        for idx, folder in enumerate(selected_module['subfolders'], start=1):
            table.add_row(str(len(selected_module['materials']) + idx), f"{folder['name']}", 'Folder')
    
    console.print()
    console.print(table)
    console.print()

    # Prompt user to select a file or folder
    while True:
        file_choice = Prompt.ask(
            "Enter the file/folder ID to select (or 'all' to download all files in this module)",
            default="all"
        )
        
        if file_choice.lower() == "all":
            console.print()

            # Calculate total items to download (including subfolder contents)
            total_items = len(selected_module['materials'])
            for subfolder in selected_module.get('subfolders', []):
                total_items += len(subfolder['materials'])
            
            with Progress() as progress:
                task = progress.add_task("[cyan]Downloading...", total=total_items)
                console.print()

                # Download files in the main module
                if selected_module['materials']:
                    download_materials(ufora, course['id'], selected_module['materials'], target_dir, task, progress)
                
                # Download files in subfolders
                for subfolder in selected_module.get('subfolders', []):
                    # Create subfolder directory
                    folder_name = re.sub(r'[<>:"/\\|?*]', '_', subfolder['name'])
                    subfolder_dir = target_dir / folder_name
                    subfolder_dir.mkdir(parents=True, exist_ok=True)
                    
                    console.print(f"[cyan]Downloading subfolder: {subfolder['name']}[/cyan]")
                    if all(material['type'] in ['Assignment', 'Discussion Topic'] for material in subfolder['materials']):
                        console.print('[yellow]No downloadable content in this folder[/yellow]')
                    if subfolder['materials']:
                        download_materials(ufora, course['id'], subfolder['materials'], subfolder_dir, task, progress)
            
            console.print(f"[green]✓ Download complete![/green]\n")
            break
        
        try:
            choice_idx = int(file_choice)
            num_materials = len(selected_module['materials'])
            num_subfolders = len(selected_module.get('subfolders', []))
            total_items = num_materials + num_subfolders
            
            if choice_idx < 1 or choice_idx > total_items:
                raise ValueError(f"Invalid ID. Please enter a number between 1 and {total_items}.")
            
            # Check if user selected a file or a subfolder
            if choice_idx <= num_materials:
                console.print()

                # User selected a file
                to_download = [selected_module['materials'][choice_idx - 1]]
                
                with Progress() as progress:
                    task = progress.add_task("[cyan]Downloading...", total=len(to_download))
                    download_materials(ufora, course['id'], to_download, target_dir, task, progress)
                
                console.print(f"[green]✓ Download complete![/green]\n")
                break
            else:
                # User selected a subfolder
                subfolder_idx = choice_idx - num_materials - 1
                selected_subfolder = selected_module['subfolders'][subfolder_idx]
                
                # Display files in the selected subfolder
                subfolder_table = Table(title=f"Available Files in {selected_subfolder['name']}", header_style="bold green")
                subfolder_table.add_column("ID", justify="right", style="bold cyan")
                subfolder_table.add_column("File Name")
                subfolder_table.add_column("Type", style="cyan")
                
                for idx, material in enumerate(selected_subfolder['materials'], start=1):
                    subfolder_table.add_row(str(idx), material['title'], material['type'])
                
                console.print()
                console.print(subfolder_table)
                console.print()
                
                # Prompt to select file(s) from subfolder
                while True:
                    subfolder_choice = Prompt.ask(
                        "Enter the file ID to select (or 'all' to download all files in this subfolder)",
                        default="all"
                    )
                    
                    if subfolder_choice.lower() == "all":
                        to_download = selected_subfolder['materials']
                    else:
                        try:
                            subfolder_file_idx = int(subfolder_choice)
                            if subfolder_file_idx < 1 or subfolder_file_idx > len(selected_subfolder['materials']):
                                raise ValueError(f"Invalid ID. Please enter a number between 1 and {len(selected_subfolder['materials'])}.")
                            
                            to_download = [selected_subfolder['materials'][subfolder_file_idx - 1]]
                        except ValueError as e:
                            console.print(f"[red]{e}[/red]")
                            continue
                    
                    # Create subfolder directory
                    folder_name = re.sub(r'[<>:"/\\|?*]', '_', selected_subfolder['name'])
                    # Add files under folder name if we are downloading to set base directory
                    if base:
                        subfolder_dir = target_dir / folder_name
                    else:
                        subfolder_dir = target_dir
                    subfolder_dir.mkdir(parents=True, exist_ok=True)
                    
                    console.print()

                    with Progress() as progress:
                        task = progress.add_task("[cyan]Downloading...", total=len(to_download))
                        if all(material['type'] in ['Assignment', 'Discussion Topic'] for material in to_download):
                            console.print('\nNo downloadable content in this folder')
                        download_materials(ufora, course['id'], to_download, subfolder_dir, task, progress)

                    console.print(f"[green]✓ Download complete![/green]\n")
                    break
                
                break
        
        except ValueError as e:
            console.print(f"[red]{e}[/red]")

@cli.command()
@click.argument('file_path', type=click.Path(exists=True))
def importtimetable(file_path):
    """Import and parse a TimeEdit timetable file, save as JSON"""
    try:
        from .timeedit_parser import parse_timeedit_file, save_timetable_json
        
        console.print("[yellow]Parsing timetable file...[/yellow]")
        timetable = parse_timeedit_file(file_path)
        
        if not timetable:
            console.print("[red]No courses found in the file[/red]")
            return
        
        # Save to config directory
        json_path = CONFIG_DIR / "timetable.json"
        save_timetable_json(timetable, str(json_path))
        
        console.print(f"[green]✓ Timetable imported successfully![/green]")
        console.print(f"[green]Saved {len(timetable)} days with courses to {json_path}[/green]")
        
    except ImportError:
        console.print("[red]Error: timeedit_parser module not found[/red]")
        console.print("[yellow]Make sure timeedit_parser.py is in the same directory[/yellow]")
    except Exception as e:
        console.print(f"[red]Error importing timetable: {e}[/red]")
        import traceback
        traceback.print_exc()

@cli.command()
@click.option('--week', '-w', is_flag=True, help='Show entire week instead of just today')
@click.option('--compact', '-c', is_flag=True, help='Hide professors column for compact view')
def timetable(week, compact):
    """Display your timetable for today (or the entire week with --week)"""
    try:
        from .timeedit_parser import load_timetable_json
        
        json_path = CONFIG_DIR / "timetable.json"
        
        if not json_path.exists():
            console.print("[red]No timetable found[/red]")
            console.print("[yellow]Import a timetable file first using:[/yellow]")
            console.print("[cyan]ufora-cli import-timetable <path_to_file>[/cyan]")
            return
        
        # Load timetable
        timetable_data = load_timetable_json(str(json_path))
        
        # Get today's date in DD-MM-YYYY format
        today = datetime.now().strftime("%d-%m-%Y")
        
        # Find today to determine week number
        current_week_num = None
        for (date_str, week_num), courses in timetable_data.items():
            if date_str == today:
                current_week_num = week_num
                break
        
        if current_week_num is None:
            console.print(f"[yellow]No courses scheduled for today ({today})[/yellow]")
            return
        
        if week:
            # Show entire week
            week_days = sorted([
                (date_str, courses) for (date_str, w), courses in timetable_data.items()
                if w == current_week_num
            ])
            
            if not week_days:
                console.print(f"[yellow]No courses scheduled for week {current_week_num}[/yellow]")
                return
            
            console.print(f"\n[bold cyan]Your Schedule for Week {current_week_num}[/bold cyan]\n")
            
            table = Table(show_header=True, header_style="bold magenta")
            table.add_column("Date", style="bold yellow", width=15)
            table.add_column("Time", style="cyan", width=20)
            table.add_column("Course", style="green", width=30)
            table.add_column("Type", style="yellow", width=15)
            table.add_column("Location", style="blue", width=30)
            if not compact:
                table.add_column("Professor(s)", style="magenta", width=25)

            for date_str, courses in week_days:
                date_obj = datetime.strptime(date_str, "%d-%m-%Y")
                day_name = date_obj.strftime("%a")
                formatted_date = date_obj.strftime("%d/%m")
                date_display = f"{day_name} {formatted_date}"

                if not courses:
                    row = [date_display, "—", "No courses", "—", "—"]
                    if not compact:
                        row.append("—")
                    table.add_row(*row)
                    continue

                for i, course in enumerate(courses):
                    professors = ", ".join(course['professors']) if course['professors'] else "—"
                    # Only show the date for the first course of the day
                    row = [
                        date_display if i == 0 else "",
                        course['time_slot'],
                        course['course_name'],
                        course['course_type'],
                        course['location']
                    ]
                    if not compact:
                        row.append(professors)
                    table.add_row(*row)

            console.print(table)
            console.print()
        
        else:
            # Show only today
            today_courses = None
            for (date_str, week_num), courses in timetable_data.items():
                if date_str == today:
                    today_courses = courses
                    break
            
            if not today_courses:
                console.print(f"[yellow]No courses scheduled for today ({today})[/yellow]")
                return
            
            # Format today's date
            date_obj = datetime.strptime(today, "%d-%m-%Y")
            day_name = date_obj.strftime("%a")
            formatted_date = date_obj.strftime("%d/%m")
            date_display = f"{day_name} {formatted_date}"
            
            console.print(f"\n[bold cyan]Your Schedule for Today (W{current_week_num}) - {date_display}[/bold cyan]\n")
            
            table = Table(show_header=True, header_style="bold magenta")
            table.add_column("Time", style="cyan", width=20)
            table.add_column("Course", style="green", width=30)
            table.add_column("Type", style="yellow", width=15)
            table.add_column("Location", style="blue", width=30)
            if not compact:
                table.add_column("Professor(s)", style="magenta", width=25)
            
            for course in today_courses:
                professors = ", ".join(course['professors']) if course['professors'] else "—"
                row = [
                    course['time_slot'],
                    course['course_name'],
                    course['course_type'],
                    course['location']
                ]
                if not compact:
                    row.append(professors)
                table.add_row(*row)
            
            console.print(table)
            console.print()
        
    except ImportError:
        console.print("[red]Error: timeedit_parser module not found[/red]")
    except Exception as e:
        console.print(f"[red]Error loading timetable: {e}[/red]")
        import traceback
        traceback.print_exc()

@cli.command()
@click.argument('directory')
def directory(directory):
    """Set the base directory for course materials"""
    path = Path(directory).expanduser().resolve()
    
    if not path.exists():
        console.print(f"[yellow]Directory doesn't exist. Creating: {path}[/yellow]")
        path.mkdir(parents=True, exist_ok=True)
    
    config = load_config()
    config['base_directory'] = str(path)
    save_config(config)
    
    console.print(f"[green]✓ Base directory set to: {path}[/green]")

@cli.command()
@click.argument('email')
def email(email):
    """Set your UGent email address to be used in login"""
    config = load_config()
    config['email'] = email
    save_config(config)
    
    console.print(f"[green]✓ UGent email set to: {email}[/green]")

@cli.command()
@click.argument('method', type=click.Choice(['app', 'sms'], case_sensitive=False))
def twofa(method):
    """Set your 2FA method (app or sms)"""
    config = load_config()
    config['2fa_method'] = method.lower()
    save_config(config)
    
    console.print(f"[green]✓ 2FA method set to: {method}[/green]")


if __name__ == '__main__':
    cli()
import requests
import time
import re
import random
import string
import threading
from concurrent.futures import ThreadPoolExecutor
from queue import Queue, Empty
from rich.console import Console
from rich.text import Text

console = Console()
log_q = Queue()
write_lock = threading.Lock()

#put ur name if u want to chenge yes but my name now cuz am cool
DOMAIN_LABEL = "daapiandev.ontop!"
PROXIES_FILE = "proxies.txt"
counter_lock = threading.Lock()
unverified_count = 0
verified_count = 0

_title_lock = threading.Lock()
_last_title = None
_title_stop = threading.Event()

try:
    import ctypes
    _is_windows = True
    _SetConsoleTitle = ctypes.windll.kernel32.SetConsoleTitleW
except Exception:
    _is_windows = False
    _SetConsoleTitle = None

def set_console_title(title: str):
    global _last_title
    if not _is_windows or _SetConsoleTitle is None:
        return
    with _title_lock:
        if title == _last_title:
            return
        try:
            _SetConsoleTitle(title)
            _last_title = title
        except Exception:
            pass

def title_updater(poll_interval=0.5):
    prev_u = prev_v = -1
    while not _title_stop.is_set():
        with counter_lock:
            u = unverified_count
            v = verified_count
        if u != prev_u or v != prev_v:
            title = f"{DOMAIN_LABEL} U:({u}) V:({v})"
            set_console_title(title)
            prev_u, prev_v = u, v
        time.sleep(poll_interval)

def incr_unverified():
    global unverified_count
    with counter_lock:
        unverified_count += 1

def decr_unverified():
    global unverified_count
    with counter_lock:
        if unverified_count > 0:
            unverified_count -= 1

def incr_verified():
    global verified_count
    with counter_lock:
        verified_count += 1

def load_proxies(filename=PROXIES_FILE):
    try:
        with open(filename, "r") as f:
            return [line.strip() for line in f if line.strip()]
    except Exception:
        return []

def save_credentials(email, password):
    with write_lock:
        with open("accs.txt", "a") as f:
            f.write(f"{email}:{password}\n")

def create_temp_inbox(session):
    try:
        r = session.post('https://api.tempmail.lol/v2/inbox/create',
                         json={"captcha": None, "domain": None, "prefix": ""}, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None

def check_inbox(session, token):
    try:
        r = session.get(f'https://api.tempmail.lol/v2/inbox?token={token}', timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None

def generate_password():
    up = random.choice(string.ascii_uppercase)
    low = ''.join(random.choices(string.ascii_lowercase, k=6))
    sp = random.choice("!@#$%^&*()-_=+")
    p = list(up + low + sp); random.shuffle(p); return ''.join(p)

def send_tunnelbear_create_account(session, email, password):
    try:
        r = session.post("https://prod-api-core.tunnelbear.com/core/web/createAccount",
                         data={"email": email, "password": password, "json": "1", "v": "web-1.0"}, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None

def extract_verification_links(content):
    return re.findall(r'https://api\.tunnelbear\.com/core/verifyEmail\?key=[\w-]+', content or "")

def process_verification_link(session, link):
    try:
        r = session.get(link, timeout=10)
        with write_lock:
            with open("genned.txt", "a") as f:
                f.write(f"{link}: HTTP {r.status_code}\n")
        return r.status_code == 200
    except Exception:
        return False

def ui_log(task_id, level, message, email_hint=None):
    ts = time.strftime("%H:%M:%S")
    t = Text()
    t.append(f"[{DOMAIN_LABEL}] ", style="bold cyan")
    t.append(f"[{ts}] ", style="magenta")
    lvl = level.upper()
    if level in ("debug", "info"):
        lvl_style = "bold yellow"
    elif level == "success":
        lvl_style = "bold green"
    elif level == "warning":
        lvl_style = "bold bright_yellow"
    else:
        lvl_style = "bold red"
    t.append(f"[{lvl}] ", style=lvl_style)
    t.append("-> ", style="white")
    t.append(message, style="green")
    if email_hint:
        t.append("  " + email_hint, style="dim white")
    log_q.put(t)

def printer_loop(stop_event):
    buffer = []
    max_lines = 200
    header = Text()
    header.append(f"{DOMAIN_LABEL}  ", style="bold cyan")
    with counter_lock:
        header.append("U: ", style="white"); header.append(f"({unverified_count}) ", style="bold yellow")
        header.append("V: ", style="white"); header.append(f"({verified_count})", style="bold green")
    header.append("    " + time.strftime("%Y-%m-%d %H:%M:%S"), style="dim")
    console.print(header)
    console.print("-" * console.width)
    while not stop_event.is_set() or not log_q.empty():
        try:
            t = log_q.get(timeout=0.25)
            buffer.insert(0, t)
            if len(buffer) > max_lines:
                buffer.pop()
            console.print(t)
            while True:
                try:
                    t = log_q.get_nowait()
                    buffer.insert(0, t)
                    if len(buffer) > max_lines:
                        buffer.pop()
                    console.print(t)
                except Empty:
                    break
        except Empty:
            pass

def worker(task_id, proxies):
    session = requests.Session()
    chosen = None
    if proxies:
        chosen = random.choice(proxies)
        session.proxies = {"http": f"socks5h://{chosen}", "https": f"socks5h://{chosen}"}
        ui_log(task_id, "info", f"Using proxy {chosen}")

    ui_log(task_id, "debug", "Debug: Creating temporary inbox")
    temp = create_temp_inbox(session)
    if not temp:
        ui_log(task_id, "error", "Debug: Failed to create temporary inbox")
        return
    email = temp.get("address"); token = temp.get("token")
    if not email or not token:
        ui_log(task_id, "error", "Debug: Incomplete inbox data")
        return

    incr_unverified()
    ui_log(task_id, "debug", f"Debug: Temporary Email Generated: {email}", email_hint=email)

    pwd = generate_password()
    ui_log(task_id, "debug", "Debug: Generated password")
    resp = send_tunnelbear_create_account(session, email, pwd)
    ui_log(task_id, "info", "Debug: TunnelBear account creation response received" if resp else "Debug: TunnelBear account creation failed")
    save_credentials(email, pwd)

    processed = set(); verified = False
    ui_log(task_id, "debug", "Debug: Starting inbox check for verification link")
    while not verified:
        inbox = check_inbox(session, token)
        if inbox:
            emails = inbox.get("emails", [])
            ui_log(task_id, "debug", f"Debug: Getting emails for {email} (found {len(emails)})")
            for e in emails:
                content = e.get("html") or e.get("body", "")
                for link in extract_verification_links(content):
                    if link in processed: continue
                    processed.add(link)
                    ui_log(task_id, "info", f"Debug: Processing verification link {link.split('key=')[-1][:8]}...", email_hint=email)
                    if process_verification_link(session, link):
                        verified = True
                        decr_unverified()
                        incr_verified()
                        ui_log(task_id, "success", f"Debug: Account verified for {email}", email_hint=email)
                        break
                if verified: break
        else:
            ui_log(task_id, "warning", f"Debug: Failed to retrieve inbox data for {email}", email_hint=email)
        if not verified:
            time.sleep(2)
    ui_log(task_id, "success", f"Debug: Finished {email}", email_hint=email)

def styled_input_prompt():
    """
    Prints a single-line styled prompt that matches the log style and reads an integer.
    Keeps the prompt visually consistent with the debug lines.
    """
    while True:
        ts = time.strftime("%H:%M:%S")
        prompt = Text()
        prompt.append(f"[{DOMAIN_LABEL}] ", style="bold cyan")
        prompt.append(f"[{ts}] ", style="magenta")
        prompt.append("[INPUT] ", style="bold blue")
        prompt.append("-> ", style="white")
        prompt.append("How many accounts to generate: ", style="green")

        console.print(prompt, end="")
        raw = console.input("", markup=False)
        raw = raw.strip()
        if not raw:
            console.print("[bold yellow]Please enter a number.[/bold yellow]")
            continue
        try:
            n = int(raw)
            if n <= 0:
                console.print("[bold yellow]Enter a positive integer.[/bold yellow]")
                continue
            return n
        except ValueError:
            console.print("[bold red]Invalid number. Try again.[/bold red]")

if __name__ == "__main__":
    num_accounts = styled_input_prompt()

    proxies = load_proxies(PROXIES_FILE)

    title_thread = threading.Thread(target=title_updater, daemon=True)
    title_thread.start()

    stop_event = threading.Event()
    printer = threading.Thread(target=printer_loop, args=(stop_event,), daemon=True)
    printer.start()

    with ThreadPoolExecutor(max_workers=num_accounts) as ex:
        futures = [ex.submit(worker, i, proxies) for i in range(1, num_accounts + 1)]
        for f in futures:
            try:
                f.result()
            except Exception as e:
                ui_log(0, "error", f"Worker exception: {e}")

    _title_stop.set()
    stop_event.set()
    title_thread.join(timeout=1)
    printer.join(timeout=1)

    with counter_lock:
        final_title = f"{DOMAIN_LABEL}  U:({unverified_count}) V:({verified_count})"
    set_console_title(final_title)
    console.print("\n[bold green]All account tasks completed.[/bold green]")


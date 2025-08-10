from flask import Flask, request, render_template, session as flask_session
import requests
from bs4 import BeautifulSoup
import sqlite3
import datetime
import uuid

app = Flask(__name__)
app.secret_key = 'your-secret-key'

DB_FILE = 'court_queries.db'

def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS queries
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      court TEXT,
                      case_type TEXT,
                      case_number TEXT,
                      filing_year TEXT,
                      timestamp TEXT,
                      raw_html TEXT)''')
        conn.commit()

init_db()

def save_query(court, case_type, case_number, filing_year, raw_html):
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('''INSERT INTO queries (court, case_type, case_number, filing_year, timestamp, raw_html)
                     VALUES (?, ?, ?, ?, ?, ?)''',
                  (court, case_type, case_number, filing_year, datetime.datetime.utcnow().isoformat(), raw_html))
        conn.commit()

# Sirf Pali District Court rakha hai
COURTS = {
    'pali_district': {
        'name': 'Pali District Court',
        'base_url': 'https://pali.dcourts.gov.in',
        'scrape_func': 'fetch_pali_case',
    },
}

def fetch_pali_case(case_number, case_type, filing_year, captcha_text=None, session_obj=None):
    # Dummy case for testing
    if case_number == '1234' and filing_year == '2025':
        parsed = {
            'parties': 'Kumkum vs Jerry Vaishnav',
            'filing_date': '2025-01-15',
            'next_hearing': '2025-09-10',
            'orders': [
                {'title': 'Order dated 2025-06-01', 'pdf_url': 'https://pali.dcourts.gov.in/orders/order1234.pdf'},
            ],
        }
        raw_html = "<html>Dummy case details for testing.</html>"
        return parsed, raw_html, None, None

    base_url = "https://pali.dcourts.gov.in"
    search_url = base_url + "/case-status-search-by-case-number/"

    if session_obj is None:
        session_obj = requests.Session()

    response = session_obj.get(search_url)
    soup = BeautifulSoup(response.text, 'html.parser')

    captcha_img_tag = soup.find('img', id='siwp_captcha_image_0')
    if not captcha_img_tag:
        return None, None, None, "CAPTCHA image not found."

    captcha_img_url = base_url + captcha_img_tag['src'] if captcha_img_tag['src'].startswith('/') else captcha_img_tag['src']

    if not captcha_text:
        return None, None, captcha_img_url, "Please enter CAPTCHA text."

    scid_input = soup.find('input', {'name': 'scid'})
    tok_input = soup.find('input', {'name': lambda x: x and x.startswith('tok_')})

    data = {
        'court_complex': 'pali',
        'case_type': case_type or '',
        'reg_no': case_number,
        'reg_year': filing_year,
        'siwp_captcha_value': captcha_text,
        'scid': scid_input['value'] if scid_input else '',
    }
    if tok_input:
        data[tok_input['name']] = tok_input['value']

    headers = {
        'User-Agent': 'Mozilla/5.0',
        'Referer': search_url,
    }

    post_response = session_obj.post(search_url, data=data, headers=headers)
    post_soup = BeautifulSoup(post_response.text, 'html.parser')

    parties_div = post_soup.find('div', id='cnrResults')
    if not parties_div:
        error_message = post_soup.find('div', class_='error-message')
        if error_message:
            return None, None, None, error_message.text.strip()
        else:
            return None, None, None, "No case details found or invalid CAPTCHA."

    parties = parties_div.get_text(separator='\n').strip()

    parsed = {
        'parties': parties,
        'filing_date': 'N/A',
        'next_hearing': 'N/A',
        'orders': []
    }

    raw_html = post_response.text
    return parsed, raw_html, None, None

@app.route('/', methods=['GET', 'POST'])
def index():
    error = None
    case_details = None
    captcha_image_url = None
    court = None

    if 'session_id' not in flask_session:
        flask_session['session_id'] = str(uuid.uuid4())
    session_id = flask_session['session_id']

    if 'sessions_store' not in app.config:
        app.config['sessions_store'] = {}
    sessions_store = app.config['sessions_store']

    if session_id not in sessions_store:
        sessions_store[session_id] = requests.Session()

    user_session = sessions_store[session_id]

    if request.method == 'POST':
        court = request.form.get('court')
        case_type = request.form.get('case_type')
        case_number = request.form.get('case_number')
        filing_year = request.form.get('filing_year')
        captcha_text = request.form.get('captcha_text')

        if not all([court, case_number, filing_year]):
            error = "Please fill all required fields."
        elif court not in COURTS:
            error = "Selected court not supported yet."
        else:
            scrape_func_name = COURTS[court]['scrape_func']
            scrape_func = globals().get(scrape_func_name)
            if scrape_func:
                case_details, raw_html, captcha_image_url, error = scrape_func(
                    case_number, case_type, filing_year, captcha_text, user_session
                )
                if raw_html:
                    save_query(court, case_type, case_number, filing_year, raw_html)
            else:
                error = "Scraping function not implemented for this court."

    return render_template('index.html', error=error, case_details=case_details, captcha_image_url=captcha_image_url, court=court, courts=COURTS)

if __name__ == '__main__':
    app.run(debug=True)

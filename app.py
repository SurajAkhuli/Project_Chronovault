from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
from dotenv import load_dotenv
import atexit
import os
# Add this right after the imports and before load_dotenv()
import time
APP_START_TIME = time.time()

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__, template_folder='templates')
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///chronovault.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)
app.config['SESSION_PERMANENT'] = False
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'


# Mail configuration
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER')
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS', 'True').lower() == 'true'
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER')


# Initialize extensions
db = SQLAlchemy(app)
mail = Mail(app)

# Database Models
class User(db.Model):
    """User model for authentication"""
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    
    # Relationship with messages
    messages = db.relationship('TimeMessage', backref='author', lazy=True)
    
    def set_password(self, password):
        """Hash and set password"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Check if provided password matches hash"""
        return check_password_hash(self.password_hash, password)

class TimeMessage(db.Model):
    """Model for time-locked messages"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    recipient_email = db.Column(db.String(120), nullable=False)
    delivery_datetime = db.Column(db.DateTime, nullable=False)
    delivered = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    delivered_at = db.Column(db.DateTime)

# Helper Functions
def send_time_message(message_id):
    """Send a time-locked message via email"""
    with app.app_context():
        try:
            message = TimeMessage.query.get(message_id)
            if not message or message.delivered:
                return
                    
            # Create email message
            msg = Message(
                subject='ChronoVault: Your Time-Locked Message Has Arrived!',
                recipients=[message.recipient_email],
                body=f"""Hello!

You have received a time-locked message from ChronoVault:

Message created on: {message.created_at.strftime('%Y-%m-%d %H:%M:%S')}
Scheduled delivery: {message.delivery_datetime.strftime('%Y-%m-%d %H:%M:%S')}

Your Message:
{message.content}

---
This message was sent by ChronoVault - Time-Locked Message Delivery App
                """
            )
                    
            # Send email
            mail.send(msg)
                    
            # Update message status
            message.delivered = True
            message.delivered_at = datetime.now()
            db.session.commit()
                    
            print(f"Message {message_id} delivered successfully!")
                
        except Exception as e:
            print(f"Error sending message {message_id}: {str(e)}")


def check_and_send_messages():
    """Check for messages ready to be delivered"""
    with app.app_context():
        try:
            current_time = datetime.now()
            print(f"Checking messages at: {current_time}")
            
            pending_messages = TimeMessage.query.filter(
                TimeMessage.delivered == False,
                TimeMessage.delivery_datetime <= current_time
            ).all()
            
            print(f"Found {len(pending_messages)} pending messages")
            
            for message in pending_messages:
                print(f"Sending message {message.id} scheduled for {message.delivery_datetime}")
                send_time_message(message.id)
                
        except Exception as e:
            print(f"Error in scheduler: {str(e)}")


# Initialize scheduler only once
scheduler = None

def init_scheduler():
    global scheduler
    if scheduler is None:
        scheduler = BackgroundScheduler()
        scheduler.add_job(
            func=check_and_send_messages, 
            trigger="interval", 
            minutes=1,
            id='message_checker'
        )
        scheduler.start()
        print("Scheduler started")

# Only initialize scheduler if this is the main module and not a reload
if __name__ == '__main__':
    init_scheduler()
    atexit.register(lambda: scheduler.shutdown() if scheduler else None)


# Then add this function after the models
def is_session_valid():
    """Check if session is from current app instance"""
    return session.get('app_start_time') == APP_START_TIME

# Routes
@app.route('/')
def index():
    """Home page"""
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    """User registration"""
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        
        # Validation
        if not username or not email or not password:
            flash('All fields are required!', 'error')
            return render_template('register.html')
        
        # Check if user already exists
        if User.query.filter_by(username=username).first():
            flash('Username already exists!', 'error')
            return render_template('register.html')
        
        if User.query.filter_by(email=email).first():
            flash('Email already registered!', 'error')
            return render_template('register.html')
        
        # Create new user
        user = User(username=username, email=email)
        user.set_password(password)
        
        db.session.add(user)
        db.session.commit()
        
        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """User login"""
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            session['user_id'] = user.id
            session['username'] = user.username
            session['app_start_time'] = APP_START_TIME  # Add this line
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password!', 'error')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    """User logout"""
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

@app.route('/dashboard')
def dashboard():
    """User dashboard"""
    if 'user_id' not in session or not is_session_valid():
        session.clear()
        flash('Please login to access dashboard.', 'info')
        return redirect(url_for('login'))
        
    user = db.session.get(User, session['user_id'])
    if not user:
        session.clear()
        flash('Session expired. Please login again.', 'info')
        return redirect(url_for('login'))
    
    messages = TimeMessage.query.filter_by(user_id=user.id).order_by(TimeMessage.created_at.desc()).all()
    return render_template('dashboard.html', user=user, messages=messages)



@app.route('/create_message', methods=['GET', 'POST'])
def create_message():
    """Create a new time-locked message"""
    if 'user_id' not in session:
        flash('Please login to create messages.', 'info')
        return redirect(url_for('login'))
    
    user = db.session.get(User, session['user_id'])
    if not user:
        session.clear()
        flash('Session expired. Please login again.', 'info')
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        content = request.form['content']
        recipient_email = request.form['recipient_email']
        delivery_date = request.form['delivery_date']
        delivery_time = request.form['delivery_time']
        
        # Validation
        if not content or not recipient_email or not delivery_date or not delivery_time:
            flash('All fields are required!', 'error')
            return render_template('create_message.html')
        
        # Parse delivery datetime
        try:
            delivery_datetime = datetime.strptime(f"{delivery_date} {delivery_time}", "%Y-%m-%d %H:%M")
            
            # Check if delivery time is in the future
            if delivery_datetime <= datetime.now():
                flash('Delivery time must be in the future!', 'error')
                return render_template('create_message.html')
            
        except ValueError:
            flash('Invalid date or time format!', 'error')
            return render_template('create_message.html')
        
        # Create new message
        message = TimeMessage(
            user_id=session['user_id'],
            content=content,
            recipient_email=recipient_email,
            delivery_datetime=delivery_datetime
        )
        
        db.session.add(message)
        db.session.commit()
        
        flash('Time-locked message created successfully!', 'success')
        return redirect(url_for('dashboard'))
    
    return render_template('create_message.html')

@app.route('/test_email')
def test_email():
    """Test email functionality"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    try:
        msg = Message(
            subject='ChronoVault Test Email',
            recipients=[User.query.get(session['user_id']).email],
            body='This is a test email from ChronoVault!'
        )
        mail.send(msg)
        flash('Test email sent successfully!', 'success')
    except Exception as e:
        flash(f'Email error: {str(e)}', 'error')
    
    return redirect(url_for('dashboard'))

# Initialize database
# @app.before_first_request
# def create_tables():
#     """Create database tables"""
#     db.create_all()

# if __name__ == '__main__':
#     with app.app_context():
#         db.create_all()
#     app.run(debug=True)

if __name__ == '__main__':
    # Clear any existing sessions on startup
    with app.app_context():
        db.create_all()
    
    # Initialize scheduler
    init_scheduler()
    
    try:
        app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False)
    finally:
        if scheduler:
            scheduler.shutdown()

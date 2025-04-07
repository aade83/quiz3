from flask import Flask, request, jsonify
import google.generativeai as genai
from datetime import datetime, timedelta
import jwt
import bcrypt
import smtplib
import certifi
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pymongo import MongoClient

app = Flask(__name__)
app.config['SECRET_KEY'] = 'asdfghjklzxcvbnm'

genai.configure(api_key="AIzaSyB05YYb4DG9Y_FWW5pSK8yQUSK2fyfPZP4")

# MongoDB setup with SSL fix
client = MongoClient("mongodb+srv://yadavaditya8324:8324aditya@cluster0.zm9hyv3.mongodb.net/y", tlsCAFile=certifi.where())
db = client['quiz_db']
users_collection = db['users']
results_collection = db['results']
quizzes_collection = db['quizzes']  # New collection to store quizzes by skill
user_attempts = {}

def generate_token(username):
    expiration = datetime.utcnow() + timedelta(days=1)
    token = jwt.encode({"username": username, "exp": expiration}, app.config['SECRET_KEY'], algorithm="HS256")
    return token

def authenticate_user(token):
    try:
        data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
        return data["username"]
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

def send_email(recipient_email, subject, body):
    sender_email = "your_email@example.com"
    sender_password = "your_email_password"  # Use an app password for Gmail

    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = recipient_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    try:                
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, recipient_email, msg.as_string())
        server.quit()
        print("Email sent successfully!")
    except Exception as e:
        print(f"Failed to send email: {e}")

@app.route('/register', methods=['POST'])
def register():
    data = request.json
    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        return jsonify({"error": "Username and password are required"}), 400

    if users_collection.find_one({"username": username}):
        return jsonify({"error": "User already exists"}), 400
     
    hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    users_collection.insert_one({"username": username, "password": hashed_password})
    return jsonify({"message": "User registered successfully"}), 201

@app.route('/login', methods=['POST'])
def login():
    data = request.json
    username = data.get("username")
    password = data.get("password")

    user = users_collection.find_one({"username": username})
    if not user or not bcrypt.checkpw(password.encode('utf-8'), user['password'].encode('utf-8')):
        return jsonify({"error": "Invalid credentials"}), 401

    token = generate_token(username)
    return jsonify({"token": token})

def generate_quiz(skill):
    # Check if quiz for this skill already exists in the database
    existing_quiz = quizzes_collection.find_one({"skill": skill})
    
    if existing_quiz:
        print(f"Found existing quiz for {skill}")
        return existing_quiz["questions"]
    
    # If not, generate new questions
    print(f"Generating new quiz for {skill}")
    model = genai.GenerativeModel("gemini-2.0-flash")
    prompt = f"Generate 20 multiple-choice questions related to {skill}. Include 4 options and the correct answer. Format: question, options, correct answer."
    response = model.generate_content(prompt)
    questions = response.text
    
    # Store the generated quiz in the database
    quizzes_collection.insert_one({
        "skill": skill,
        "questions": questions,
        "created_at": datetime.utcnow()
    })
    
    return questions

def evaluate_quiz(questions, user_answers):
    score = 0
    correct_answers = [q['correct'] for q in questions]

    for i in range(len(questions)):
        if user_answers[i] == correct_answers[i]:
            score += 1

    return score

@app.route('/generate_quiz', methods=['POST'])
def get_quiz():
    token = request.headers.get("Authorization")
    if not token:
        return jsonify({"error": "Token is required"}), 401
    
    username = authenticate_user(token)
    if not username:
        return jsonify({"error": "Invalid or expired token"}), 401
    
    data = request.json
    skill = data.get("skill")
    expert_email = data.get("email")
    
    if not skill or not expert_email:
        return jsonify({"error": "Skill and expert email are required"}), 400
    
    if username in user_attempts:
        last_attempt = user_attempts[username]
        if datetime.now() - last_attempt < timedelta(days=90):
            return jsonify({"error": "You can retake the test after 90 days."}), 403

    user_attempts[username] = datetime.now()
    
    # Get quiz questions (either from DB or newly generated)
    questions = generate_quiz(skill)
    
    # Send email to expert with test link
    test_link = f"http://yourdomain.com/take_test?skill={skill}"  # Replace with actual test link
    email_subject = "Quiz Test Link"
    email_body = f"Dear Expert,\n\nPlease find the test link for the {skill} skill below:\n{test_link}\n\nBest regards,\nQuiz Team"
    send_email(expert_email, email_subject, email_body)
    
    return jsonify({"questions": questions})
  
@app.route('/submit_quiz', methods=['POST'])
def submit_quiz():
    token = request.headers.get("Authorization")
    if not token:
        return jsonify({"error": "Token is required"}), 401

    username = authenticate_user(token)
    if not username:
        return jsonify({"error": "Invalid or expired token"}), 401

    data = request.json
    questions = data.get("questions")
    user_answers = data.get("answers")
    if not questions or not user_answers:
        return jsonify({"error": "Questions and answers are required"}), 400
    score = evaluate_quiz(questions, user_answers)    
    # Save result to database
    results_collection.insert_one({"username": username, "score": score, "date_taken": datetime.utcnow()})    
    return jsonify({"score": score})

# New route to list available quizzes
@app.route('/available_quizzes', methods=['GET'])
def available_quizzes():
    token = request.headers.get("Authorization")
    if not token:
        return jsonify({"error": "Token is required"}), 401
    
    username = authenticate_user(token)
    if not username:
        return jsonify({"error": "Invalid or expired token"}), 401
    
    # Get all unique skills from the quizzes collection
    quizzes = list(quizzes_collection.find({}, {"skill": 1, "created_at": 1, "_id": 0}))
    
    return jsonify({"quizzes": quizzes})

if __name__ == '__main__':
    app.run(debug=True)
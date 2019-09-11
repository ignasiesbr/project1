import os
import requests
from flask import Flask, session, render_template, request, redirect, flash, jsonify
from flask_session import Session
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from passlib.hash import pbkdf2_sha256

app = Flask(__name__)

# Check for environment variable
if not os.getenv("DATABASE_URL"):
    raise RuntimeError("DATABASE_URL is not set")

# Configure session to use filesystem
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Set up database
engine = create_engine(os.getenv("DATABASE_URL"))
db = scoped_session(sessionmaker(bind=engine))


@app.route("/")
def index():
    return render_template("index.html")

@app.route("/log-in")
def login_index():
    if not session.get("logged-in"):
        return render_template("login.html")
    else:
        return render_template("search.html", username=session["username"])


@app.route("/search", methods=["POST", "GET"])
def login():

    if request.method == "POST":
        if session.get("logged-in"):
            return render_template("search.html", username=session["username"])

        formUser = request.form.get("username")
        formPassword = request.form.get("password")
        res = db.execute("SELECT id, password FROM users WHERE username=:username", {"username":formUser}).fetchone()
        userId = res[0]
        if not res:
            return render_template("error.html")

        dbHashedPw = res.password
        if pbkdf2_sha256.verify(formPassword, dbHashedPw):
            session["logged-in"] = True
            session["username"] = formUser
            session["user_id"] = userId
            return render_template("search.html", username=session["username"])
        else:
            flash('invalid credentials', 'error ')
            return redirect("/log-in")

    else:
        if session["logged-in"]:
            return render_template("search.html", username=session["username"])
        else:
            return redirect("/log-in")



@app.route("/sign-up")
def signup_index():
    if session.get("logged-in"):
        return render_template("search.html", username=session["username"])
    return render_template("signup.html")

def existsUsername(username):
    return db.execute("SELECT * FROM users WHERE username = :username", {"username":username}).rowcount != 0

@app.route("/sign-up/success", methods=["POST"])
def signup():
    uname = request.form.get("username")
    pwd1 = request.form.get("password1")
    pwd2 = request.form.get("password2")
    if existsUsername(uname) or pwd1 != pwd2 or pwd1 is None or pwd2 is None:
        return render_template("error.html")
    hashedPw = pbkdf2_sha256.hash(pwd1)
    db.execute("INSERT INTO users (username, password) VALUES (:name, :password)", {"name":uname, "password":hashedPw})
    db.commit()
    return render_template("success-signup.html")


@app.route("/log-out")
def logout():
    session["logged-in"] = False
    return render_template("index.html")


@app.route("/results", methods=["POST"])
def results():
    search = request.form.get("search-text")
    query = "%" + str(search) + "%"
    books = db.execute("SELECT id, isbn, title,author,year FROM books WHERE isbn LIKE :query OR title LIKE :query OR author LIKE :query LIMIT 20", {"query":query})
    if books.rowcount == 0:
        return render_template("error.html")

    return render_template("results.html", books=books)

@app.route("/book/<int:book_id>", methods=["GET", "POST"])
def book(book_id):

    if request.method == "GET":

        abook = db.execute("SELECT isbn, title, author, year FROM books WHERE id = :book_id", {"book_id":book_id}).fetchone()
        if abook is None:
            return render_template("error.html")

        reviews = db.execute("SELECT review, rating, username FROM reviews WHERE book_id=:book_id", {"book_id":book_id}).fetchall()

        #API DATA
        apiRes = requests.get("https://www.goodreads.com/book/review_counts.json", params={"key": os.getenv(key_api),  "isbns":abook.isbn})
        goodreadsReview = apiRes.json()
        nratingsGoodReads = goodreadsReview["books"][0]["ratings_count"]
        avgGoodReads = goodreadsReview["books"][0]["average_rating"]


        return render_template("book.html", isbn=abook.isbn, title=abook.title, author=abook.author, year=abook.year,
                                reviews=reviews, avgGoodReads=avgGoodReads,nratingsGoodReads=nratingsGoodReads)

    else:
        rate = request.form.get("rating")
        review = request.form.get("review")
        existingReview = db.execute("SELECT * FROM reviews WHERE user_id = :user_id AND book_id=:book_id", {"user_id":session["user_id"], "book_id":book_id})
        if existingReview.rowcount == 1:
            return render_template("error.html")

        rate = int(rate)
        db.execute("INSERT INTO reviews (review, book_id, user_id, rating, username) VALUES (:review, :book_id, :user_id, :rating, :username)",
                   {"review":review, "book_id":book_id, "user_id":session["user_id"], "rating":rate, "username":session["username"]})
        db.commit()
        return redirect("/book/" + str(book_id))



@app.route("/api/<isbn>")
def isbn_api(isbn):
    areReview = db.execute("SELECT isbn, review FROM books JOIN reviews ON books.id = reviews.book_id WHERE isbn=:isbn", {"isbn":isbn}).fetchall()
    if areReview:
        book = db.execute("SELECT title, author, year, isbn, COUNT(reviews.id) as review_count, AVG(reviews.rating) as average_score \
                          FROM books JOIN reviews on books.id = reviews.book_id WHERE isbn =:isbn GROUP BY title, \
                          author, year, isbn", {"isbn": isbn}).fetchone()
    else:
        book = db.execute("SELECT title, author, year, isbn FROM books WHERE isbn=:isbn", {"isbn":isbn}).fetchone()

    if not book:
        return jsonify({"error":"Invalid ISBN"}),422

    if areReview:
        #Make it JSON serializable
        avg_score = float('%.2f'%book.average_score)
        return jsonify({
            "title": book.title,
            "author": book.author,
            "year": book.year,
            "isbn": book.isbn,
            "review_count":book.review_count,
            "average_score":avg_score
        })
    else:
        return jsonify({
            "title": book.title,
            "author": book.author,
            "year": book.year,
            "isbn": book.isbn,
            "review_count": 0,
            "average_score": 0
        })




from hashlib import new
import os
from models import db, connect_db, User, Instrument, Playlist, Song, Like, PlaylistUser, Message, Friend
from forms import EditUserForm, UserLoginForm, NewUserForm
from flask import Flask, render_template, redirect, request, flash, session, g, jsonify, url_for
from flask_debugtoolbar import DebugToolbarExtension
from sqlalchemy.exc import IntegrityError
import requests
from json import loads


app = Flask(__name__)


CURR_USER_KEY = "curr_user"


app.config['SQLALCHEMY_DATABASE_URI'] = (
    os.environ.get('DATABASE_URL', 'postgresql:///tabular'))
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ECHO'] = False
app.config['DEBUG_TB_INTERCEPT_REDIRECTS'] = False
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', "it's a secret")

toolbar = DebugToolbarExtension(app)

connect_db(app)

CURR_USER_KEY = 'curr_user'


@app.before_request
def add_user_to_g():
    """If we're logged in, add curr user to Flask global."""

    if CURR_USER_KEY in session:
        g.user = User.query.get(session[CURR_USER_KEY])

    else:
        g.user = None


def do_login(user):
    """Log in user."""

    session[CURR_USER_KEY] = user.id


def do_logout():
    """Logout user."""

    if CURR_USER_KEY in session:
        del session[CURR_USER_KEY]


def get_instrument_choices():
    """Get all instruments and construct instrument choice tuples to pass to select field"""

    choices = [(0, 'Select Your Instrument')]

    instruments = Instrument.query.all()

    for instrument in instruments:

        choices.append(
            (instrument.id, instrument.name))

    return choices


def add_song_if_new(**kwargs):
    """Add a song to the database"""

    if Song.query.filter_by(id=kwargs['id']).first():
        return None

    song = Song(**kwargs)
    db.session.add(song)
    db.session.commit()


@app.route('/')
@app.route('/index')
def index():
    """Direct user to the welcome page if not logged in, and landing page if logged in."""
    if g.user:

        return render_template('users/current/dashboard.html', user=g.user)

    else:
        return render_template('welcome.html')


# Routes for user authentication


@app.route('/register', methods=["GET", "POST"])
def register():
    """Handle user signup.

    Create new user and add to DB.

    If form not valid, present form.

    If the there already is a user with that username: flash message
    and re-present form.
    """

    form = NewUserForm()

    if form.validate_on_submit():
        try:
            user = User.register(
                username=form.username.data,
                password=form.password.data,
                email=form.email.data,
                first_name=form.first_name.data or None,
                last_name=form.last_name.data or None
            )
            db.session.commit()

        except IntegrityError:
            form.username.errors.append('Username already taken!')
            return render_template('users/register.html', form=form)

        do_login(user)

        return redirect("/")

    else:
        return render_template('users/register.html', form=form)


@app.route('/login', methods=["GET", "POST"])
def login():
    """Handle user login."""

    form = UserLoginForm()

    if g.user:

        return redirect('/')

    if form.validate_on_submit():
        user = User.authenticate(form.username.data,
                                 form.password.data)

        if user:
            do_login(user)
            flash(f"Hello, {user.username}!", "success")
            return redirect("/")

        form.username.errors.append("Invalid credentials.")

    return render_template('users/login.html', form=form)


@app.route('/logout')
def logout():
    """Handle logout of user."""

    do_logout()

    return redirect('/')


@app.route('/search')
def search_page():
    """Display search page."""

    if not g.user:
        flash('Access Unauthorized! Please Login', 'danger')

        return redirect('/')

    return render_template('search.html', user=g.user)


# **************
# User routes
# **************

@app.route('/users/<int:user_id>/profile')
def user_profile(user_id):
    """Display user profile page given a user ID"""

    # Check that a user is logged in, if not redirect
    if not g.user:
        flash('Access Unauthorized! Please Login', 'danger')

        return redirect('/')

    # If the user ID is 0, display the user page for currently logged in user. Else, show
    # page of user matching user ID
    if user_id == 0:
        return render_template('users/current/my_profile.html', user=g.user)

    user = User.query.get(user_id)

    my_friends = User.get_friends(g.user.id)

    return render_template('users/profile.html', user=user, my_friends=my_friends)


@app.route('/users/profile/edit', methods=['GET', 'POST'])
def edit_my_profile():
    """Display page to edit current user's profile information"""

    # Check that a user is logged in, if not redirect
    if not g.user:
        flash('Access Unauthorized! Please Login', 'danger')

        return redirect('/')

    # Load edit form and populate instrument dropdown with choices from instruments in database
    form = EditUserForm(obj=g.user)
    form.instrument_id.choices = get_instrument_choices()

    # If form is validated, update user in database
    if form.validate_on_submit():

        try:
            for key, value in form.data.items():

                if key == 'instrument_id' and value == 0:
                    g.user.instrument = None
                else:
                    setattr(g.user, key, value)

        # error handling for duplicate username
        except IntegrityError:
            form.username.errors.append('Username already taken!')
            return render_template('users/current/edit_profile.html', user=g.user, form=form)

        db.session.add(g.user)
        db.session.commit()

        return redirect(request.referrer)

    # If get request, render the form
    return render_template('users/current/edit_profile.html', user=g.user, form=form)


@app.route('/users/likes', methods=['POST'])
def toggle_like():
    """Add or remove a song from a user's liked songs"""

    # Check that a user is logged in, if not redirect
    if not g.user:
        flash('Access Unauthorized! Please Login', 'danger')

        return redirect('/')

    # Get the song info and add the song to the database if it isn't in the database
    data = loads(request.json['json'])
    add_song_if_new(**data)

    # check if the song is in the user's likes
    liked_song = Like.query.filter(
        Like.song_id == data['id'], Like.user_id == g.user.id).first()

    # If it is in the likes, remove it
    if liked_song:
        db.session.delete(liked_song)
        db.session.commit()
        return 'Song successfully removed from your liked songs!'

    # If it is not in the likes, add it
    else:
        new_like = Like(user_id=g.user.id, song_id=data['id'])
        db.session.add(new_like)
        db.session.commit()
        return 'Song successfully added to your liked songs!'


@app.route('/users/<int:user_id>/playlists', methods=['GET', 'POST'])
def user_playlists(user_id):
    """
    GET request: display a list of the user's playlists, given a user id

    POST request: create a new playlist, given the user id matches the currently logged in user
    """

    # Check that a user is logged in
    if not g.user:
        flash('Access Unauthorized! Please Login', 'danger')

        return redirect('/')

    # Check for POST request

    if request.method == 'POST':

        # Check that the user id is the same as the currently logged in user.
        # Users cannot create a playlist for another user
        if user_id == g.user.id:

            name = request.form['playlist-name']

            # Do not allow user to create a playlist with a duplicate name
            is_duplicate = Playlist.query.filter(
                Playlist.user_id == g.user.id, Playlist.name == name).one_or_none()

            if is_duplicate:
                return 'this is a duplicate!'
            else:
                # Create a new playlist and add a playlist user
                new_playlist = Playlist(name=name, user_id=g.user.id)
                db.session.add(new_playlist)
                db.session.commit()
                playlist_user = PlaylistUser(
                    playlist_id=new_playlist.id, user_id=g.user.id)
                db.session.add(playlist_user)
                db.session.commit()

                return redirect(url_for('user_playlists', user_id=0))

    if user_id == 0:
        # If user id is 0, direct to logged in user's playlists
        return render_template('users/current/my_playlists.html', user=g.user)

    user = User.query.get_or_404(user_id)

    return render_template('playlists/playlists.html', user=user)


@app.route('/users/request-friend/<int:user_id>', methods=["POST"])
def send_friend_request(user_id):
    """Send a friend request to a user, given a user ID"""

    # Check that a user is logged in
    if not g.user:
        flash('Access Unauthorized! Please Login', 'danger')

        return redirect('/')

    if g.user.check_if_friends(user_id):

        flash('You are already friends!')
        return redirect(request.referrer)

    # Create a friend request message to user matching user ID
    g.user.send_friend_request(user_id)
    db.session.commit()

    return redirect(request.referrer)


@app.route('/users/accept-request/<user_id>', methods=["POST"])
def accept_friend_request(user_id):

    # Check that a user is logged in
    if not g.user:
        flash('Access Unauthorized! Please Login', 'danger')

        return redirect('/')

    if g.user.check_if_friends(user_id):

        flash('You are already friends!')
        return redirect(request.referrer)

    g.user.accept_friend_request(user_id)
    db.session.commit()

    return redirect(request.referrer)


@app.route('/users/deny-request/<user_id>', methods=["POST"])
def deny_friend_request(user_id):

    # Check that a user is logged in
    if not g.user:
        flash('Access Unauthorized! Please Login', 'danger')

        return redirect('/')

    if g.user.deny_friend_request(user_id):
        db.session.commit()

    return redirect(request.referrer)


@app.route('/users/<int:user_id>/friends')
def show_friends(user_id):

    # Check that a user is logged in
    if not g.user:
        flash('Access Unauthorized! Please Login', 'danger')

        return redirect('/')

    if user_id == 0:

        return render_template('users/current/my_friends.html', user=g.user)


@app.route('/users/remove-friend/<user_id>', methods=["POST"])
def remove_friend(user_id):

    if not g.user:
        flash('Access Unauthorized! Please Login', 'danger')

        return redirect('/')

    if not g.user.check_if_friends(user_id):

        flash('You are not friends!')
        return redirect(request.referrer)

    g.user.remove_friend(user_id)
    db.session.commit()

    return redirect(url_for('show_friends', user_id=0))


# *************
# Routes for playlists
# *************


@ app.route('/playlists/<int:playlist_id>')
def show_playlist(playlist_id):
    """Display page for a playlist, given a playlist id"""

    # Check that a user is logged in
    if not g.user:
        flash('Access Unauthorized! Please Login', 'danger')

        return redirect('/')

    # If playlist_id is zero, direct to current user's liked songs page
    if playlist_id == 0:
        return render_template('playlists/likes.html', user=g.user)

    playlist = Playlist.query.get_or_404(playlist_id)

    return render_template('playlists/playlist.html', playlist=playlist, user=g.user)


@ app.route('/playlists/<int:playlist_id>/delete', methods=["POST"])
def delete_playlist(playlist_id):
    """Delete a playlist from the database if the currently logged in user is the creator
    of the playlist
    """

    playlist = Playlist.query.get_or_404(playlist_id)

    # Check that a user is logged in, if not redirect
    if not g.user:
        flash('Access Unauthorized! Please Login', 'danger')

        return redirect('/')

    # Check that the playlist creator is the same as the logged in user, if not redirect
    if g.user.id != playlist.creator.id:
        flash("You may not delete another user's playlist!")
        return redirect('/')

    # Delete the playlist from the database and redirect to current user's playlists page
    db.session.delete(playlist)
    db.session.commit()
    return redirect(url_for('user_playlists', user_id=0))


@ app.route('/playlists/add-song', methods=["POST"])
def add_song_to_playlist():
    """Add a song to a playlist"""

    # Check that a user is logged in, if not redirect
    if not g.user:
        flash('Access Unauthorized! Please Login', 'danger')

        return redirect('/')

    # Get the data from the post request JSON object
    data = loads(request.json['json'])

    # Get song info and add to the database if the song is not already saved
    songInfo = data['songInfo']
    add_song_if_new(**songInfo)

    # Create an array of database ID's from the playlists passed in the JSON object,
    # then get all playlists from the database that have matching ID's
    playlists = [playlist['id'] for playlist in data['playlists']]
    playlists = Playlist.query.filter(Playlist.id.in_(playlists)).all()

    # Loop over the playlists and add the song to each one. If the playlist creator ID does not
    # match the currently logged in user, redirect
    for playlist in playlists:

        if playlist.user_id != g.user.id:
            flash("You may not add a song to another user's playlist")
            return redirect('/')

        playlist.add_song(songInfo['id'])

    db.session.commit()

    return redirect(request.referrer)


@ app.route('/playlists/<int:playlist_id>/remove-song', methods=["POST"])
def remove_song_from_playlist(playlist_id):
    """Remove a song from a playlist given a playlist ID"""

    # Check that a user is logged in, if not redirect
    if not g.user:
        flash('Access Unauthorized! Please Login', 'danger')

        return redirect('/')

    # Get song info from the post request body
    songInfo = loads(request.json['json'])

    # Get playlist from the database
    playlist = Playlist.query.get_or_404(playlist_id)

    # Check that playlist creator ID matches the currently logged in user ID, if not redirect
    if playlist.user_id != g.user.id:
        flash("You may not remove a song from another user's playlist")
        return redirect('/')

    # remove the song from the playlist
    playlist.remove_song(songInfo['id'])
    db.session.commit()

    return redirect(request.referrer)


# *******************
# Routes for messages
# *******************

@ app.route('/messages')
def show_messages():

    if not g.user:
        flash('Access Unauthorized! Please Login', 'danger')

        return redirect('/')

    return render_template('users/current/messages.html', messages=g.user.received_msgs)


# *****************
# API ENDPOINTS
# ****************


@ app.route('/api/likes')
def get_liked_songs():
    """Returns a list of song ID's for all liked songs in the database"""

    # If a user is not logged in, return an empty list
    if not g.user:
        liked_songs = []

    liked_songs = [song.id for song in g.user.likes]

    return jsonify(liked_songs)


@ app.route('/api/users')
def get_users():
    """Returns a list of users' info from the database"""

    query = request.args.get('query')

    # If a query is provided, search the database using the query. Otherwise get all users
    if query:
        users = User.query.filter(User.username.ilike(f'%{query}%')).all()
    else:
        users = User.query.all()

    # Remove currently logged in user from the list of users
    if g.user and g.user in users:
        idx = users.index(g.user)
        users.pop(idx)

    if users:
        users = [user.serialize() for user in users]

    else:
        users = []

    return jsonify(users)


@ app.route('/api/songs/<int:song_id>/playlists')
def get_playlists_for_song(song_id):
    """
    Returns a list of id's for all current user's playlists that a song is present in
    """

    # If a user is not logged in, return an empty list
    if not g.user:
        playlistIds = []

    # Get song from database
    song = Song.query.filter(Song.id == song_id).one_or_none()

    # If song is in database, return a list of playlist IDs. Only playlists that were created by the
    # currently logged in user and contain the song are returned. If the song is not found in the
    # database, return an empty list
    if song:
        playlistIds = [playlist.id
                       for playlist in song.playlists if playlist.creator.id == g.user.id]
    else:
        playlistIds = []

    return jsonify(playlistIds)

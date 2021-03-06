import os
import tempfile
import pytest
import json
import pdb
import unittest
from backend import app, db, bcrypt, mail
from backend.models.user import User, UserSchema, user_schema, Role
from backend.models.client_templates import ClientTemplate, ClientSession, ClientExercise, CheckIn, TrainingEntry
from backend.models.coach_templates import CoachTemplate, CoachSession, CoachExercise, Exercise
from flask_sqlalchemy import SQLAlchemy
from flask_session import Session
from datetime import datetime as dt
from datetime import date, timedelta
from flask_mail import Mail

DATE_FORMAT = '%Y-%m-%d'

#  ----------------- SETUP -----------------

# Test client object that should be used when creating test clients
test_client = {
    'first_name': 'test',
    'last_name': 'client',
    'email': 'test@client.com',
    'password': 'fakepassword',
    'role': 'CLIENT'
}

# Test client object that should be used when creating test coaches
test_coach = {
    'first_name': 'test',
    'last_name': 'coach',
    'email': 'test@coach.com',
    'password': 'fakepassword',
    'role': 'COACH'
}

# Creates the app test client so that we can use it to call endpoints in our applicatoin
@pytest.fixture(scope='function')
def client(request):
    test_client = app.test_client()
    return test_client

# Database fixture. We create an in-memory SQlite database and use this for all tests. That way
# we don't put stress on our production database. It's important here that the scope is set to function
# so that the transactions are rolled back on every transaction
@pytest.fixture(scope='function')
def _db():
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
    # Comment above and uncomment below to persist the database to the local folder structure
    # app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///test.db"
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['TESTING'] = True
    assert app.testing

    mail = Mail(app)

    # Create sessions table to handle login sessions
    session = Session(app)
    session.app.session_interface.db.create_all()

    # We migrate the model into the sqlite database. It will create all tables based on the schema.
    # We need to use the production database in order to migrate the data because the models are attached to this
    # object
    db.create_all()

    return db

#  ------------------------------------- CONFIGURATION TEST -------------------------------------

# Test that the mocked db_session works and doesn't persist beyond the scope of a test
def test_a_transaction(db_session):
    user = User(
        first_name=test_client['first_name'], last_name=test_client['last_name'],
        email=test_client['email'], password=test_client['password'],
        role=test_client['role'], verified=False
    )

    db_session.add(user)
    db_session.commit()

def test_transaction_doesnt_persist(db_session):
    user = db_session.query(User).filter_by(email=test_client['email']).first()
    assert user == None

def test_health(client):
    resp, code = request(client, 'GET', '/health')
    assert code == 200
    assert resp == {'success': True}

#  ------------------------------------- USER TESTS -------------------------------------
def role_check(client, db_session, request_type, url):
    client_user = sign_up_user_for_testing(client, test_client)
    assert client_user['user'] != None
    assert client_user['user']['role'] == 'CLIENT'

    # Sign in as the client
    login_resp = login_user_for_testing(client, test_client)
    assert login_resp['user']['id'] != None and login_resp['user']['id'] != ""

    resp, code = request(client, request_type, url)
    return resp, code
    


def test_signup(client, db_session):
    resp = sign_up_user_for_testing(client, test_client)
    del resp['user']['id']
    assert resp ==\
        {
            'user': {
                'approved': False,
                'check_in': None,
                'coach_id': None,
                'email': test_client['email'],
                'first_name': test_client['first_name'],
                'last_name': test_client['last_name'],
                'reset_token': None,
                'role': test_client['role'],
                'verified': False
            }
        }

def test_verify_client(client, db_session):
    # Create an unapproved user
    resp = sign_up_user_for_testing(client, test_client)
    assert resp['user']['approved'] == False

    # Query the user so we can grab the verification token
    user = User.query.filter_by(email=resp['user']['email']).first()
    assert user != None
    assert user.verification_token != None and user.verification_token != ""

    # Approve the user using his verification token
    url = '/verifyUser?verification_token={}&email={}'.format(user.verification_token, user.email)
    resp, code = request(client, "GET", url)

    # Refresh the user and check that they have been verified
    user = User.query.get(user.id)
    assert user.verified == True

    # Check that the server redirected the client
    assert code == 302
    assert resp == None

def test_client_list(client, db_session):
    # Sign up a coach so that sign is as a coach.
    user = sign_up_user_for_testing(client, test_coach)
    assert user['user'] != None
    assert user['user']['role'] == 'COACH'

    # Sign into the coach
    login_resp = login_user_for_testing(client, test_coach)
    assert login_resp['user']['id'] != None and login_resp['user']['id'] != ""

    # Populate the database with approved, unapproved and past clients
    clients = [
        User(
            first_name='test1', last_name='test1',
            email='test1@user.com', password='fakepassword',
            role='CLIENT', verified=False, approved=None
        ),
        User(
            first_name='test2', last_name='test2',
            email='test2@user.com', password='fakepassword',
            role='CLIENT', verified=False, approved=True
        ),
        User(
            first_name='test3', last_name='test3',
            email='test3@user.com', password='fakepassword',
            role='CLIENT', verified=False, approved=False
        )
    ]
    db_session.bulk_save_objects(clients)
    db_session.commit()

    # Grab the clients through the endpoint
    clients_resp, code = request(client, "GET", '/clientList')
    assert clients_resp != None and code == 200
    
    # Check that the clients are returned
    assert len(clients_resp['approvedClients']) != 0
    assert len(clients_resp['unapprovedClients']) != 0
    assert len(clients_resp['pastClients']) != 0

def test_update_profile(client, db_session):
    # sign up as client
    client_user = sign_up_user_for_testing(client, test_client)
    assert client_user['user'] != None
    assert client_user['user']['role'] == 'CLIENT'

    # login as client
    login_resp = login_user_for_testing(client, test_client)
    assert login_resp['user']['id'] != None and login_resp['user']['id'] != ""

    data = {
        'first_name': 'changed first name',
        'last_name': 'changed last name',
        'email': 'changed@email.com',
        'password': 'changedpassword',
        'oldpassword': 'fakepassword'
    }

    # make updates
    resp, code = request(client, "PUT", '/updateProfile', data=data)
    assert resp != None and code == 200
    assert resp['user']['first_name'] == 'changed first name'
    assert resp['user']['last_name'] == 'changed last name'
    assert resp['user']['email'] == 'changed@email.com'

    # call updates with no data to test that nothing happens
    resp, code = request(client, "PUT", '/updateProfile', data={})
    assert code == 200


# def test_logout(client):
#     new_user = create_new_user()
#     signup_rv = sign_up_user_for_testing(client, new_user)
#     login_rv = login_user_for_testing(client, new_user)
#     logout_rv = client.get("auth/logout")
#     assert logout_rv.json == {'success': True}

# forgot password and reset password have to be tested in the same endpoint because all db transactions are
# rolled back after the test ends (the user will lose their reset_token)
def test_forgot_password_flow(client, db_session):
     # sign up as client
    client_user = sign_up_user_for_testing(client, test_client)
    assert client_user['user'] != None
    assert client_user['user']['email'] == 'test@client.com'
    assert client_user['user']['reset_token'] == None

    # pass email to endpoint
    url = '/forgotPassword?email={}'.format(client_user['user']['email'])
    resp, code = request(client, "GET", url)
    assert code == 200 and resp != None
    assert resp['success'] == True

    # check to see that a reset token was created for the user
    user = User.query.get(client_user['user']['id'])
    assert user != None
    assert user.reset_token != None

    # reset the users password with the generated reset_token and a new password
    data = {
        'password': 'testchangepassword',
        'reset_token': user.reset_token
    }
    resp, code = request(client, "POST", 'resetPassword', data=data)
    assert code == 200 and resp != None
    assert resp['success'] == True

    # Query the user again and check that the password has changed.
    # TODO: Refreshing doesn't work for some reason
    user = User.query.get(client_user['user']['id'])
    assert bcrypt.check_password_hash(user.password, data['password'].encode(encoding='utf-8'))

def test_terminate_client(client, db_session):
    # sign up a coach
    coach_user = sign_up_user_for_testing(client, test_coach)
    assert coach_user['user'] != None
    assert coach_user['user']['role'] == 'COACH'

    # sign up a client
    client_user = sign_up_user_for_testing(client, test_client)
    assert client_user['user'] != None
    assert client_user['user']['role'] == 'CLIENT'

    data = {
        "id": client_user['user']['id']
    }

    # remove a client with insufficient permissions, should return 400
    resp, code = request(client, "PUT", '/terminateClient', data=data)
    assert code == 400 and resp != None
    assert resp['error'] == 'Expected role of COACH'

    # login as coach
    login_resp = login_user_for_testing(client, test_coach)
    assert login_resp['user']['id'] != None and login_resp['user']['id'] != ""

    # remove a client logged in as coach, should succeed
    resp, code = request(client, "PUT", '/terminateClient', data=data)
    assert code == 200 and resp != None
    assert resp['user']['approved'] == None

def test_delete_user(client, db_session):
    # sign up a client to delete
    client_user = sign_up_user_for_testing(client, test_client)
    assert client_user['user'] != None
    assert client_user['user']['role'] == 'CLIENT'

    # sign up a coach
    coach_user = sign_up_user_for_testing(client, test_coach)
    assert coach_user['user'] != None
    assert coach_user['user']['role'] == 'COACH'

    # login as coach
    login_resp = login_user_for_testing(client, test_coach)
    assert login_resp['user']['id'] != None and login_resp['user']['id'] != ""

    # Delete user with no id parameter, check that 400 is returned
    url = "/user"
    resp, code = request(client, "DELETE", url)
    assert code == 400
    assert resp['error'] == 'No id parameter found in request query'

    # Delete user with no bogus id, check that 404 is returned
    url = "/user?id={}".format(420)
    resp, code = request(client, "DELETE", url)
    assert code == 404
    assert resp['error'] == 'No user found with passed id'

    # Delete user
    db_session.expire_all()
    db_session.begin_nested()
    url = "/user?id={}".format(client_user['user']['id'])
    resp, code = request(client, "DELETE", url)

def test_get_user(client, db_session):
    # sign up a client
    client_user = sign_up_user_for_testing(client, test_client)
    assert client_user['user'] != None
    assert client_user['user']['role'] == 'CLIENT'

    # get client with invalid credentials. should return 400
    url = '/getUser?id={}'.format(client_user['user']['id'])
    resp, code = request(client, "GET", url)
    assert code == 400
    assert resp['error'] == 'Expected role of COACH'

    # sign up a coach
    coach_user = sign_up_user_for_testing(client, test_coach)
    assert coach_user['user'] != None
    assert coach_user['user']['role'] == 'COACH'

    # login as coach
    login_resp = login_user_for_testing(client, test_coach)
    assert login_resp['user']['id'] != None and login_resp['user']['id'] != ""

    # get client with no id parameter, should return 404
    url = '/getUser'
    resp, code = request(client, "GET", url)
    assert code == 404
    assert resp['error'] == 'No id parameter found in request'

    # get client with bogus id, should return 404
    url = '/getUser?id={}'.format(420)
    resp, code = request(client, "GET", url)
    assert code == 404
    assert resp['error'] == 'Invalid id'

    # get client
    url = '/getUser?id={}'.format(client_user['user']['id'])
    resp, code = request(client, "GET", url)
    assert code == 200 and resp != None
    assert resp['user']['id'] == client_user['user']['id']

def test_approve_client(client, db_session):
    # sign up a coach
    coach_user = sign_up_user_for_testing(client, test_coach)
    assert coach_user['user'] != None
    assert coach_user['user']['role'] == 'COACH'

    # login as coach
    login_resp = login_user_for_testing(client, test_coach)
    assert login_resp['user']['id'] != None and login_resp['user']['id'] != ""

    # create the user to approve
    user = User(
        first_name='Test', last_name='Test', email='test@test.com', password='test', role='CLIENT',
        verified=True, approved=False
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    data = {
        'id': user.id
    }
    resp, code = request(client, "PUT", "/approveClient", data=data)
    assert code == 200
    assert resp != None
    assert resp['Approved'] != None

    current_db_session = db_session.object_session(user)
    current_db_session.refresh(user)
    assert user.approved

#  ------------------------------------------- CLIENT TEMPLATES ------------------------------------------------------
def test_get_client_template(client, db_session):
    # Create and sign into the client
    user = sign_up_user_for_testing(client, test_client)
    assert user['user'] != None
    assert user['user']['role'] == 'CLIENT'

    login_resp = login_user_for_testing(client, test_client)
    assert login_resp['user']['id'] != None and login_resp['user']['id'] != ""

    # Create a template for retrieval
    template = generate_client_template_model()
    template.user_id = user['user']['id']
    db_session.add(template)
    db_session.commit()
    db_session.refresh(template)

    # Calling endpoint without client_template_id should return a 400
    url = '/client/template'
    resp, code = request(client, "GET", url)
    assert code == 400
    assert resp['error'] == 'Need to pass EITHER client_template_id or client_template_slug as a request parameter'

    # Retrieve template id
    url = '/client/template?client_template_id={}'.format(str(template.id))
    resp, code = request(client, "GET", url)
    assert code == 200
    assert resp != None
    assert resp['id'] == template.id

    # Retrieve template using slug
    url = '/client/template?client_template_slug={}'.format(template.slug)
    resp, code = request(client, "GET", url)
    assert code == 200
    assert resp != None
    assert resp['id'] == template.id

def test_get_client_templates(client, db_session):
    # Create and sign into the client
    user = sign_up_user_for_testing(client, test_client)
    assert user['user'] != None
    assert user['user']['role'] == 'CLIENT'

    login_resp = login_user_for_testing(client, test_client)
    assert login_resp['user']['id'] != None and login_resp['user']['id'] != ""

    # Create 2 templates for multiple template retrieval
    template1 = generate_client_template_model()
    template2 = generate_client_template_model()
    template1.user_id = user['user']['id']
    template2.user_id = user['user']['id']
    db_session.add(template1)
    db_session.add(template2)
    db_session.commit()
    db_session.refresh(template1)
    db_session.refresh(template2)

    # Check that we get a 400 back if we don't supply the user_id
    url = '/client/templates'
    resp, code = request(client, "GET", url)
    assert code == 400
    assert resp['error'] == 'No query parameter user_id found in request'

    url = '/client/templates?user_id={}'.format(str(user['user']['id']))
    resp, code = request(client, "GET", url)
    assert code == 200
    assert len(resp['templates']) == 2
    assert resp['templates'][0]['id'] == template1.id or resp['templates'][0]['id'] == template2.id
    assert resp['templates'][1]['id'] == template1.id or resp['templates'][1]['id'] == template2.id

def test_post_client_template(client, db_session):
    # Create a coach to create the template and a client to assign it to
    coach_user = sign_up_user_for_testing(client, test_coach)
    assert coach_user['user'] != None
    assert coach_user['user']['role'] == 'COACH'

    client_user = sign_up_user_for_testing(client, test_client)
    assert client_user['user'] != None
    assert client_user['user']['role'] == 'CLIENT'

    # Sign in as the coach
    login_resp = login_user_for_testing(client, test_coach)
    assert login_resp['user']['id'] != None and login_resp['user']['id'] != ""

    # Create the client template, this function returns the coach_template used to assign to a client
    # This also creates checkins so we can check that functionality
    resp, code, coach_template = create_client_template(client, db_session, client_user['user']['id'])
    check_ins = db_session.query(CheckIn).all()
    assert code == 200
    assert resp != None
    assert resp['name'] == coach_template.name and resp['user_id'] == client_user['user']['id']
    assert check_ins != None
    assert len(check_ins) == 1
    assert check_ins[0].start_date == date.today().strftime(DATE_FORMAT)
    assert check_ins[0].end_date == (date.today() + timedelta(days=len(resp['sessions']))).strftime(DATE_FORMAT)

    # Create a second client template to test slugification
    resp, code, coach_template = create_client_template(client, db_session, client_user['user']['id'], starting_exercise_id=3)
    assert code == 200
    assert resp != None
    assert resp['slug'] == 'test-coach-template-2-test-client'

    # Create a third client template using a previous client template to test re-assigning and slugification
    client_template = ClientTemplate.query.get(resp['id'])
    assert client_template.id == resp['id']
    
    data = {
        'role': 'CLIENT',
        'template_id': client_template.id,
        'client_id': client_user['user']['id'],
    }

    # Create template without sessions, should get 400 back
    resp, code = request(client, "POST", "/client/template", data=data)
    assert code == 400
    assert resp['error'] == 'Need to specify a valid template_id (int), client_id (int), sessions (array), and role (enum)'

    data['sessions'] = []

    # Create template with empty sessions, should return 400
    resp, code = request(client, "POST", "/client/template", data=data)
    assert code == 400
    assert resp['error'] == 'Length of sessions supplied is 0'

    data['sessions'] = [
        {
            'id': client_template.sessions[0].id,
            'exercises': [
                {
                    'id': client_template.sessions[0].exercises[0].id,
                    'sets': 4,
                    'reps': 10,
                    'weight': 150
                }
            ]
        }
    ]

    resp, code = request(client, "POST", "/client/template", data=data)
    assert code == 200
    assert resp != None
    assert resp['slug'] == 'test-coach-template-2-test-client-1'
    assert resp['sessions'] != None
    assert len(resp['sessions']) == 1

    # error handling (check client_template error)
    data['template_id'] = 10
    data['role'] = 'COACH'
    resp, code = request(client, "POST", "/client/template", data=data)
    assert code == 404
    assert resp['error'] == 'No coach template found with coach_template_id: 10'

    # check error handling for user role
    data['role'] = 'User'
    resp, code = request(client, "POST", "/client/template", data=data)
    assert code == 400
    assert resp['error'] == "Parameter role should be either COACH or CLIENT" 

def test_put_client_template(client, db_session):
    # Create a coach to create the template and a client to assign it to
    coach_user = sign_up_user_for_testing(client, test_coach)
    assert coach_user['user'] != None
    assert coach_user['user']['role'] == 'COACH'

    client_user = sign_up_user_for_testing(client, test_client)
    assert client_user['user'] != None
    assert client_user['user']['role'] == 'CLIENT'

    # Sign in as the coach
    login_resp = login_user_for_testing(client, test_coach)
    assert login_resp['user']['id'] != None and login_resp['user']['id'] != ""

    # error test: pass an invalid id
    data = {
        "id": 10
    }
    resp, code = request(client, "PUT", '/client/template', data=data)
    assert code == 404
    assert resp['error'] == "No client template found with id: " + str(data['id'])

    # Create the client template, this function returns the coach_template used to assign to a client
    client_template, code, coach_template = create_client_template(client, db_session, client_user['user']['id'])
    assert code == 200
    assert client_template != None
    assert client_template['name'] == coach_template.name and client_template['user_id'] == client_user['user']['id']

    # Change name of template and ordering or sessions
    # TODO: Need to test deleting a session through this endpoint. Getting make_transient error
    data = {
        'name': 'Test Template Name Change',
        'user_id': client_user['user']['id'],
        'sessions': [
            {
                'id': client_template['sessions'][0]['id'],
                'name': 'Test Session Name Change 2',
                'order': 2
            },
            {
                'id': client_template['sessions'][1]['id'],
                'name': 'Test Session Name Change 1',
                'order': 1
            }
        ]
    }

    # Not specifying an id should return 400
    updated_client_template, code = request(client, "PUT", '/client/template', data=data)
    assert code == 400

    data['id'] = 1

    updated_client_template, code = request(client, "PUT", '/client/template', data=data)
    assert updated_client_template != None and code == 200
    assert updated_client_template['name'] == 'Test Template Name Change'
    assert len(updated_client_template['sessions']) == 2
    assert updated_client_template['sessions'][0]['name'] == 'Test Session Name Change 1' and updated_client_template['sessions'][0]['id'] == data['sessions'][1]['id']
    assert updated_client_template['sessions'][1]['name'] == 'Test Session Name Change 2' and updated_client_template['sessions'][1]['id'] == data['sessions'][0]['id']

def test_get_client_session(client, db_session):
    # Create a coach to create the template and a client to assign it to
    coach_user = sign_up_user_for_testing(client, test_coach)
    assert coach_user['user'] != None
    assert coach_user['user']['role'] == 'COACH'

    client_user = sign_up_user_for_testing(client, test_client)
    assert client_user['user'] != None
    assert client_user['user']['role'] == 'CLIENT'

    # Sign in as the coach
    login_resp = login_user_for_testing(client, test_coach)
    assert login_resp['user']['id'] != None and login_resp['user']['id'] != ""

    # Create the client template, this function returns the coach_template used to assign to a client
    client_template, code, coach_template = create_client_template(client, db_session, client_user['user']['id'])
    assert code == 200
    assert client_template != None
    assert client_template['name'] == coach_template.name and client_template['user_id'] == client_user['user']['id']

    # Retrieve a particular session from the client template
    url = '/client/session?client_session_id={}'.format(client_template['sessions'][0]['id'])
    client_session, code = request(client, 'GET', url)
    assert code == 200
    assert client_session != None
    assert client_session['id'] == client_template['sessions'][0]['id']

    # error test: pass all vars
    session_id = 10
    template_slug = "test-slug"
    session_slug = "session_slug"

    url = '/client/session?client_session_id={}&client_template_slug={}&client_session_slug={}'.format(session_id, template_slug, session_slug)
    resp, code = request(client, 'GET', url)
    assert code == 400
    assert resp['error'] == "Pass EITHER client_session_id OR client_template_slug + client_session_slug in the request parameter"

    # error test: pass template_slug != None and session_slug == None
    url = '/client/session?client_template_slug={}'.format(template_slug)
    resp, code = request(client, 'GET', url)
    assert code == 400
    assert resp['error'] == "Pass EITHER client_session_id OR client_template_slug + client_session_slug in the request parameter"

    # error test: wrong template slug
    url = '/client/session?client_template_slug={}&client_session_slug={}'.format(template_slug, session_slug)
    resp, code = request(client, 'GET', url)
    assert code == 404
    assert resp['error'] == "No client template found with slug: " + template_slug

def test_get_client_next_session(client, db_session):
    # Create a coach to create the template and a client to assign it to
    coach_user = sign_up_user_for_testing(client, test_coach)
    assert coach_user['user'] != None
    assert coach_user['user']['role'] == 'COACH'

    client_user = sign_up_user_for_testing(client, test_client)
    assert client_user['user'] != None
    assert client_user['user']['role'] == 'CLIENT'

    # Sign in as the coach
    login_resp = login_user_for_testing(client, test_coach)
    assert login_resp['user']['id'] != None and login_resp['user']['id'] != ""

    # Create the client template, this function returns the coach_template used to assign to a client
    client_template, code, coach_template = create_client_template(client, db_session, client_user['user']['id'])
    assert code == 200
    assert client_template != None
    assert client_template['name'] == coach_template.name and client_template['user_id'] == client_user['user']['id']

    # Retrieve a particular session from the client template
    url = '/client/session/next?client_id={}'.format(client_user['user']['id'])
    next_session, code = request(client, 'GET', url)
    assert code == 200
    assert next_session != None
    assert next_session['completed'] == False and next_session['client_template_id'] == client_template['id'] and client_template['active'] == True

    # check error handling
    url = '/client/session/next'
    resp, code = request(client, 'GET', url)
    assert code == 400
    assert resp['error'] == "No query parameter client_id found in request"

    # check error handling: wrong client_id
    client_id = 100
    url = '/client/session/next?client_id={}'.format(client_id)
    resp, code = request(client, 'GET', url)
    assert code == 404
    assert resp['error'] == "No active template found with client_id: " + str(client_id)

def test_post_client_session(client, db_session):
    # Create a coach to create the template and a client to assign it to
    coach_user = sign_up_user_for_testing(client, test_coach)
    assert coach_user['user'] != None
    assert coach_user['user']['role'] == 'COACH'

    client_user = sign_up_user_for_testing(client, test_client)
    assert client_user['user'] != None
    assert client_user['user']['role'] == 'CLIENT'

    # Sign in as the coach
    login_resp = login_user_for_testing(client, test_coach)
    assert login_resp['user']['id'] != None and login_resp['user']['id'] != ""

    # Create the client template, this function returns the coach_template used to assign to a client
    client_template, code, coach_template = create_client_template(client, db_session, client_user['user']['id'])
    assert code == 200
    assert client_template != None
    assert client_template['name'] == coach_template.name and client_template['user_id'] == client_user['user']['id']
    assert len(client_template['sessions']) == 2

    data1 = {
        'client_template_id': client_template['id'],
        'name': 'Feet Day 1',
        'exercises': [
            {
                "name": "Tip Toe",
                "category": "Arch",
                "sets": 3,
                "reps": 15,
                "weight": 150,
                "order": 1
		    },
        ]
    }

    data2 = {
        'client_template_id': client_template['id'],
        'name': 'Feet Day 2',
        'exercises': [
            {
                "name": "Tip Toe",
                "category": "Arch",
                "sets": 3,
                "reps": 15,
                "weight": 150,
                "order": 1
            },
        ]
    }

    # Test creating a client session as a coach (exercises should be added into exercises)
    client_session_1, code = request(client, "POST", '/client/session', data=data1)
    assert code == 200
    assert client_session_1['name'] == 'Feet Day 1'
    assert len(client_session_1['exercises']) == 1 and len(client_session_1['training_entries']) == 0

    login_resp = login_user_for_testing(client, test_client)
    assert login_resp['user']['id'] != None and login_resp['user']['id'] != ""

    client_session_2, code = request(client, "POST", '/client/session', data=data2)
    assert code == 200
    assert client_session_2['name'] == 'Feet Day 2'
    assert len(client_session_2['exercises']) == 0 and len(client_session_2['training_entries']) == 1

    # error test: missing arg
    data3 = {
        'name': 'Feet Day 1',
        'exercises': [
            {
                "name": "Tip Toe",
                "category": "Arch",
                "sets": 3,
                "reps": 15,
                "weight": 150,
                "order": 1
		    },
        ]
    }
    resp, code = request(client, "POST", '/client/session', data=data3)
    assert code == 400
    assert resp['error'] == "Must specify client_template_id (int) name (string) and exercises (array)"

    # error test: invalid client_template_id
    data2['client_template_id'] = 100

    resp, code = request(client, "POST", '/client/session', data=data2)
    assert code == 404
    assert resp['error'] == "No client template found with template id: " + str(data2['client_template_id'])

    # error test: invalid session name
    data2['client_template_id'] = client_template['id']
    data2['name'] = 'Feet Day 1'
    resp, code = request(client, "POST", '/client/session', data=data2)
    assert code == 409
    assert resp['error'] == "Duplicate session name found in template: " + str(data2['name'])

def test_put_client_session(client, db_session):
    # Create a coach to create the template and a client to assign it to
    coach_user = sign_up_user_for_testing(client, test_coach)
    assert coach_user['user'] != None
    assert coach_user['user']['role'] == 'COACH'

    client_user = sign_up_user_for_testing(client, test_client)
    assert client_user['user'] != None
    assert client_user['user']['role'] == 'CLIENT'

    # Sign in as the coach
    login_resp = login_user_for_testing(client, test_coach)
    assert login_resp['user']['id'] != None and login_resp['user']['id'] != ""

    # Create the client template, this function returns the coach_template used to assign to a client
    client_template, code, coach_template = create_client_template(client, db_session, client_user['user']['id'])
    assert code == 200
    assert client_template != None
    assert client_template['name'] == coach_template.name and client_template['user_id'] == client_user['user']['id']

    # Update a particular client session, we will update the first client session. Set completed to true so we can test if the completed_date is being
    # set correctly
    data = {
        'id': client_template['sessions'][0]['id'],
        'name': 'Client session name change',
        'completed': True,
        'exercises': [
            {
                "name": "Deadlifts",
                "category": "Lower Back",
                "sets": 1,
                "reps": 1,
                "weight": 100,
                "order": 1
		    }
        ]
    }

    resp, code = request(client, "PUT", '/client/session', data=data)
    assert code == 200
    assert resp != None
    assert len(resp['exercises']) == 1
    assert resp['name'] == 'Client session name change'
    assert resp['completed'] == True
    assert resp['completed_date'] == (date.today() + timedelta(days=resp['order'])).strftime(DATE_FORMAT)

    # test error: wrong id
    data['id'] = 100
    resp, code = request(client, "PUT", '/client/session', data=data)
    assert code == 404
    assert resp['error'] == "No client session found with supplied id"
    # test error: missing id
    del data['id']
    resp, code = request(client, "PUT", '/client/session', data=data)
    assert code == 400
    assert resp['error'] == "No id parameter found in request body"


def test_get_active_client_template(client, db_session):
    # Create and sign into the client
    user = sign_up_user_for_testing(client, test_client)
    assert user['user'] != None
    assert user['user']['role'] == 'CLIENT'

    login_resp = login_user_for_testing(client, test_client)
    assert login_resp['user']['id'] != None and login_resp['user']['id'] != ""

    # Create 2 templates so that we can grab the specific active template. We also want to check if there are 2
    # active templates that the response returns a 409 error code
    template1 = generate_client_template_model(active=True)
    template2 = generate_client_template_model(active=True)
    template1.user_id = user['user']['id']
    template2.user_id = user['user']['id']
    db_session.add(template1)
    db_session.add(template2)
    db_session.commit()
    db_session.refresh(template1)
    db_session.refresh(template2)

    url = '/client/template/active'
    resp, code = request(client, "GET", url)
    assert code == 400 and resp['error'] == 'No query parameter user_id found in request'

    url = '/client/template/active?user_id={}'.format(user['user']['id'])
    resp, code = request(client, "GET", url)
    assert code == 409 and resp['error'] == "More than 1 active template found for client"

    # Update one of the templates to not be active (template 2). IMPORTANT to update and delete objects you have to grab the current session
    # that is handling the specific template
    template2.active = False
    current_db_session = db_session.object_session(template2)
    current_db_session.commit()

    url = '/client/template/active?user_id={}'.format(user['user']['id'])
    resp, code = request(client, "GET", url)
    assert code == 200
    assert resp != None
    assert resp['id'] == template1.id

#  ------------------------------------- HELPER METHODS -------------------------------------

# sign up a user. It returns the user response. It also error checks
def sign_up_user_for_testing(client, user):
    mimetype = 'application/json'
    headers = {
        'Content-Type': mimetype,
        'Accept': mimetype
    }
    # Set test to true so that an album isn't created for the user
    data = {
        'first_name': user['first_name'],
        'last_name': user['last_name'],
        'email': user['email'],
        'password': user['password'],
        'role': user['role'],
        'test': True
    }
    
    resp = client.post('signUp', data=json.dumps(data), headers=headers)

    assert resp.json != None
    assert resp._status_code == 200

    return resp.json

# request is a helper method to make a request with the application client
def request(client, method, url, data=None):
    mimetype = 'application/json'
    headers = {
        'Content-Type': mimetype,
        'Accept': mimetype
    }

    resp = None
    if method == "GET":
        resp = client.get(url)
    elif method == "POST":
        resp = client.post(url, data=json.dumps(data), headers=headers)
    elif method == "PUT":
        resp = client.put(url, data=json.dumps(data), headers=headers)
    elif method == "DELETE":
        resp = client.delete(url)

    return resp.json, resp._status_code

# test http guard 

# Logs a user in. Input user should contain email and password. It also error checks
def login_user_for_testing(client, user):
    mimetype = 'application/json'
    headers = {
        'Content-Type': mimetype,
        'Accept': mimetype
    }
    data = {
        'email': user['email'],
        'password': user['password']
    }

    resp = client.post("/auth/login", data=json.dumps(data), headers=headers)

    assert resp.json != None
    assert resp._status_code == 200

    return resp.json

def logout_user_for_testing(client):
    resp = client.get("/auth/logout")

    assert resp.json != None
    assert resp._status_code == 200

    return resp.json

def generate_client_template_model(active=True):
    return ClientTemplate(
        name='Test Client Template', slug='test-client-template', start_date='2020-12-12', completed=False, active=active, sessions=[
            ClientSession(
                name='Test Session 1', order=1, completed=False, completed_date='2020-12-13', slug='test-session-1', exercises=[
                    ClientExercise(
                        sets=3, reps=12, weight=225, category='Lower Back', name='Deadlifts', order=1
                    )
                ]
            )
        ]
    )

# This method generates a CoachTemplate model and adds the corresponding exercises to the database.
# The CoachTemplate will have 2 coach sessions with 2 exercises each
def generate_coach_template_model(db_session, id):
    db_session.add(Exercise(id=id, category='Lower Back', name='Deadlifts'))
    db_session.add(Exercise(id=id + 1, category='Latisimus Dorsi', name='Pullups'))
    db_session.commit()
    if id == 1:
        name = 'Test Coach Template'
        slug = 'test-coach-template'
    elif id == 3:
        name = 'Test Coach Template 2'
        slug = 'test-coach-template-2'

    return CoachTemplate(
        id=id, name=name, slug=slug, sessions=[
            CoachSession(
                name='Test Session 1', slug='test-session-1', order=1, coach_exercises=[
                    CoachExercise(
                        exercise_id=id, order=1,
                    ),
                    CoachExercise(
                        exercise_id=id + 1, order=2
                    )
                ]
            ),
            CoachSession(
                name='Test Session 2', slug='test-session-2', order=2, coach_exercises=[
                    CoachExercise(
                        exercise_id=id, order=1
                    ),
                    CoachExercise(
                        exercise_id=id + 1, order=2
                    )
                ]
            )
        ]
    )

# This method creates a client template by first creating a coach_template, then assigning it to a client.
# It returns (response, code, coach_template)
def create_client_template(client, db_session, client_id, starting_exercise_id=1, role='COACH'):
    # Create a coach template to assign to a client
    coach_template = generate_coach_template_model(db_session, starting_exercise_id)
    db_session.add(coach_template)
    db_session.commit()
    db_session.refresh(coach_template)
    
    # Create a client template using this coach template and assign it to the client
    data = {
        'template_id': coach_template.id,
        'client_id': client_id,
        'sessions': [],
        'role': role
    }
    # Specify the sets, reps and weight of the coach exercises within the sessions
    for coach_session in coach_template.sessions:
        session = {'id': coach_session.id, 'exercises': []}
        for coach_exercise in coach_session.coach_exercises:
            session['exercises'].append({
                'id': coach_exercise.id,
                'sets': 5,
                'reps': 5,
                'weight': 315
            })
        data['sessions'].append(session)

    resp, code = request(client, "POST", '/client/template', data=data)
    return resp, code, coach_template


def create_coach_template(client, db_session):
    # Create a coach template to assign to a client
    coach_template = generate_coach_template_model(db_session, 1)
    
    data = {
        'name': coach_template.name,
        'sessions': []
    }
    # # Specify the sets, reps and weight of the coach exercises within the sessions
    for coach_session in coach_template.sessions:
        session = {'name': coach_session.name, 'order': coach_session.order, 'coach_exercises': []}
        for coach_exercise in coach_session.coach_exercises:
            session['coach_exercises'].append({
                'exercise_id': coach_exercise.exercise_id,
                'order': coach_exercise.order
            })
        data['sessions'].append(session)
    
    resp, code = request(client, "POST", '/coach/template', data=data)
    return resp, code, coach_template

def create_coach_template_alt(client, db_session):
    # Create a coach template to assign to a client
    coach_template = generate_coach_template_model(db_session, 3)
    
    data = {
        'name': coach_template.name,
        'sessions': []
    }
    # # Specify the sets, reps and weight of the coach exercises within the sessions
    count = 0
    for coach_session in coach_template.sessions:
        session = {'name': coach_session.name, 'order': coach_session.order, 'coach_exercises': []}
        for coach_exercise in coach_session.coach_exercises:
            session['coach_exercises'].append({
                'name': "exercise_name" + "_" + str(count),
                'category': "exercise_category" + "_" + str(count),
                'order': coach_exercise.order
            })
            count += 1
        data['sessions'].append(session)
    
    resp, code = request(client, "POST", '/coach/template', data=data)
    return resp, code, coach_template



#  ------------------------------------- COACH TEMPLATES -------------------------------------
def test_get_coach_template(client, db_session):
    result, code = role_check(client, db_session, "GET", '/coach/template')
    assert code == 401
    assert result['error'] == "Expected role of COACH"
    # Create and sign into the client
    coach = sign_up_user_for_testing(client, test_coach)
    assert coach['user'] != None
    assert coach['user']['role'] == 'COACH'

    login_resp = login_user_for_testing(client, test_coach)
    assert login_resp['user']['id'] != None and login_resp['user']['id'] != ""

    # test enpoint without creating templates, should result in an error
    url = '/coach/template'
    resp, code = request(client, "GET", url)
    assert code == 400
    assert resp['error'] == "Pass EITHER coach_template_id OR coach_template_slug in the request parameter"
    
    # test slug
    slug = "test-fail"
    url = '/coach/template?coach_template_slug={}'.format(slug)
    slug_resp, code = request(client, "GET", url)
    assert slug_resp['error'] == "Coach_template not found with given slug: " + slug

    # template_id
    template_id = 10
    url = '/coach/template?coach_template_id={}'.format(template_id)
    slug_resp, code = request(client, "GET", url)
    assert slug_resp['error'] == "Coach_template not found with given id: " + str(template_id) 

    # Create a template for retrieval
    template = generate_coach_template_model(db_session, 1)
    db_session.add(template)
    db_session.commit()
    db_session.refresh(template)

    # Retrieve template using api
    url = '/coach/template?coach_template_id={}'.format(str(template.id))
    resp, code = request(client, "GET", url)
    assert code == 200
    assert resp != None
    assert resp['id'] == template.id

    # call endpoint with tempalte slug
    template_slug = template.slug
    url = '/coach/template?coach_template_slug={}'.format(template_slug)
    resp, code = request(client, "GET", url)
    assert code == 200
    assert resp != None
    assert resp['id'] == template.id


def test_get_coach_templates(client, db_session):
    # role check
    result, code = role_check(client, db_session, "GET", '/coach/templates')
    assert code == 401
    assert result['error'] == "Expected role of COACH"
   
    # Create and sign into the coach
    coach = sign_up_user_for_testing(client, test_coach)
    assert coach['user'] != None
    assert coach['user']['role'] == 'COACH'

    login_resp = login_user_for_testing(client, test_coach)
    assert login_resp['user']['id'] != None and login_resp['user']['id'] != ""

   # Create 2 templates for multiple template retrieval
    template1 = generate_coach_template_model(db_session, 1)
    template2 = generate_coach_template_model(db_session, 3)
    db_session.add(template1)
    db_session.add(template2)
    db_session.commit()
    db_session.refresh(template1)
    db_session.refresh(template2)

    resp, code = request(client, "GET", '/coach/templates')
    assert code == 200
    assert len(resp['templates']) == 2
    assert resp['templates'][0]['id'] == template1.id or resp['templates'][1]['id'] == template2.id
    assert resp['templates'][1]['id'] == template1.id or resp['templates'][1]['id'] == template2.id


def test_post_coach_template(client, db_session):
    result, code = role_check(client, db_session, "POST", '/coach/template')
    assert code == 401
    assert result['error'] == "Expected role of COACH"
    # Create a coach to create the template and a client to assign it to
    coach_user = sign_up_user_for_testing(client, test_coach)
    assert coach_user['user'] != None
    assert coach_user['user']['role'] == 'COACH'

    # Sign in as the coach
    login_resp = login_user_for_testing(client, test_coach)
    assert login_resp['user']['id'] != None and login_resp['user']['id'] != ""

    # Create the coach template
    resp, code, coach_template = create_coach_template(client, db_session)
    assert code == 200
    assert resp != None
    assert resp['name'] == coach_template.name
    assert resp['slug'] == 'test-coach-template'

    # Create alternate coach template
    result, code, coach_template = create_coach_template_alt(client, db_session)
    assert code == 200
    assert result != None
    assert result['name'] == 'Test Coach Template 2'
    assert result['slug'] == 'test-coach-template-2'

def test_put_coach_template(client, db_session):
    result, code = role_check(client, db_session, "PUT", '/coach/template')
    assert code == 401
    assert result['error'] == "Expected role of COACH"
    # Create a coach to create the template and a client to assign it to
    coach_user = sign_up_user_for_testing(client, test_coach)
    assert coach_user['user'] != None
    assert coach_user['user']['role'] == 'COACH'

    # client_user = sign_up_user_for_testing(client, test_client)
    # assert client_user['user'] != None
    # assert client_user['user']['role'] == 'CLIENT'

    # Sign in as the coach
    login_resp = login_user_for_testing(client, test_coach)
    assert login_resp['user']['id'] != None and login_resp['user']['id'] != ""

    # Create the coach template, this function returns the coach_template used to assign to a client
    resp, code, coach_template = create_coach_template(client, db_session)
    assert code == 200
    assert resp != None
    assert resp['name'] == coach_template.name

    # Change name of template and ordering or sessions
    # TODO: Need to test deleting a session through this endpoint. Getting make_transient error
    data = {
        'id': 1,
        'name': 'Test Template Name Change',
        'sessions': [
            {
                'id': resp['sessions'][0]['id'],
                'name': 'Test Session Name Change 2',
                'order': 2
            },
            {
                'id': resp['sessions'][1]['id'],
                'name': 'Test Session Name Change 1',
                'order': 1
            }
        ]
    }

    updated_coach_template, code = request(client, "PUT", '/coach/template', data=data)
    assert updated_coach_template != None and code == 200
    assert updated_coach_template['name'] == 'Test Template Name Change'
    assert len(updated_coach_template['sessions']) == 2
    assert updated_coach_template['sessions'][0]['name'] == 'Test Session Name Change 1' and updated_coach_template['sessions'][0]['id'] == data['sessions'][1]['id']
    assert updated_coach_template['sessions'][1]['name'] == 'Test Session Name Change 2' and updated_coach_template['sessions'][1]['id'] == data['sessions'][0]['id']

def test_delete_coach_template(client, db_session):
    result, code = role_check(client, db_session, "PUT", '/coach/template/delete')
    assert code == 401
    assert result['error'] == "Expected role of COACH"
    # Create and sign into the client
    coach = sign_up_user_for_testing(client, test_coach)
    assert coach['user'] != None
    assert coach['user']['role'] == 'COACH'

    login_resp = login_user_for_testing(client, test_coach)
    assert login_resp['user']['id'] != None and login_resp['user']['id'] != ""

    # Create a template for retrieval
    template = generate_coach_template_model(db_session, 1)
    db_session.add(template)
    db_session.commit()
    db_session.refresh(template)

    # Retrieve template using api
    body = {'coach_template_id': str(template.id)}

    resp, code = request(client, "PUT", '/coach/template/delete', data=body)
    assert code == 200
    assert resp != None
    assert resp['success'] == True

def test_get_coach_session(client, db_session):
    result, code = role_check(client, db_session, "GET", '/coach/session')
    assert code == 401
    assert result['error'] == "Expected role of COACH"
    # Create a coach to create the template and a client to assign it to
    coach_user = sign_up_user_for_testing(client, test_coach)
    assert coach_user['user'] != None
    assert coach_user['user']['role'] == 'COACH'

    # Sign in as the coach
    login_resp = login_user_for_testing(client, test_coach)
    assert login_resp['user']['id'] != None and login_resp['user']['id'] != ""
    
    # Create the coach template, this function returns the coach_template used to assign to a client
    resp, code, coach_template = create_coach_template(client, db_session)
    assert code == 200
    assert resp != None
    assert resp['name'] == coach_template.name

    # Retrieve a particular session from the client template
    url = '/coach/session?coach_session_id={}'.format(resp['sessions'][0]['id'])
    coach_session, code = request(client, 'GET', url)
    assert code == 200
    assert coach_session != None
    assert coach_session['id'] == resp['sessions'][0]['id']

    # call endpoint with coach_template slug and coach_session slug
    template_slug = resp['slug']
    session_slug = coach_session['slug']
    url = '/coach/session?coach_template_slug={}&coach_session_slug={}'.format(template_slug, session_slug)
    coach_session, code = request(client, 'GET', url)
    # pdb.set_trace()
    assert code == 200
    assert coach_session != None
    assert coach_session['id'] == resp['sessions'][0]['id']


def test_post_coach_session(client, db_session):
    result, code = role_check(client, db_session, "POST", '/coach/session')
    assert code == 401
    assert result['error'] == "Expected role of COACH"
    # Create a coach to create the template and a client to assign it to
    coach_user = sign_up_user_for_testing(client, test_coach)
    assert coach_user['user'] != None
    assert coach_user['user']['role'] == 'COACH'

    # Sign in as the coach
    login_resp = login_user_for_testing(client, test_coach)
    assert login_resp['user']['id'] != None and login_resp['user']['id'] != ""

    # Create the coach template, this function returns the coach_template used to assign to a client
    resp, code, coach_template = create_coach_template(client, db_session)
    assert code == 200
    assert resp != None
    assert resp['name'] == coach_template.name

    data = {
        'coach_template_id': resp['id'],
        'name': 'Feet Day',
        'coach_exercises': [
            {
                "exercise_id": 1,
                "order": 1
            },
            {
                "category": "Back",
                "name": "Deadlifts",
                "order": 2
            },
            {
                "exercise_id": 2,
                "order": 3
            }
	    ]
    }

    # Test creating a client session as a coach (exercises should be added into exercises)
    coach_session_1, code = request(client, "POST", '/coach/session', data=data)
    assert code == 200
    assert coach_session_1['name'] == 'Feet Day'
    assert coach_session_1['slug'] == 'feet-day'
    assert len(coach_session_1['coach_exercises']) == 3


def test_put_coach_session(client, db_session):
    result, code = role_check(client, db_session, "PUT", '/coach/session')
    assert code == 401
    assert result['error'] == "Expected role of COACH"
    # Create a coach to create the template and a client to assign it to
    coach_user = sign_up_user_for_testing(client, test_coach)
    assert coach_user['user'] != None
    assert coach_user['user']['role'] == 'COACH'

    # Sign in as the coach
    login_resp = login_user_for_testing(client, test_coach)
    assert login_resp['user']['id'] != None and login_resp['user']['id'] != ""

    # Create the coach template, this function returns the coach_template used to assign to a client
    resp, code, coach_template = create_coach_template(client, db_session)

    assert code == 200
    assert resp != None
    assert resp['name'] == coach_template.name

    db_session.add(Exercise(id=10, category='Lower Back', name='Deadlifts'))
    # db_session.add(Exercise(id=2, category='Latisimus Dorsi', name='Pullups'))

    # Update a particular client session, we will update the first client session
    data = {
        'id': resp['sessions'][0]['id'],
        'name': 'Coach session name change',
        'coach_exercises': [
            {
                "coach_session_id": resp['sessions'][0]['id'],
                "exercise_id": 1,
                "order": 1

		    }
        ]
    }

    resp, code = request(client, "PUT", '/coach/session', data=data)
    assert code == 200
    assert resp != None
    assert len(resp['coach_exercises']) == 1
    assert resp['name'] == 'Coach session name change'

def test_get_coach_exercise(client, db_session):
    result, code = role_check(client, db_session, "GET", '/coach/exercise')
    assert code == 401
    assert result['error'] == "Expected role of COACH"
    # Create a coach to create the template and a client to assign it to
    coach_user = sign_up_user_for_testing(client, test_coach)
    assert coach_user['user'] != None
    assert coach_user['user']['role'] == 'COACH'

    # Sign in as the coach
    login_resp = login_user_for_testing(client, test_coach)
    assert login_resp['user']['id'] != None and login_resp['user']['id'] != ""

    # Create the coach template, this function returns the coach_template used to assign to a client
    template = generate_coach_template_model(db_session, 1)
    db_session.add(template)
    db_session.commit()
    db_session.refresh(template)

    result, code = request(client, "GET", "/coach/exercise?coach_exercise_id={}".format(template.sessions[0].coach_exercises[0].id))
    
    assert code == 200
    assert result != None
    assert result['id'] == template.sessions[0].coach_exercises[0].id


def test_get_exercises(client, db_session):
    result, code = role_check(client, db_session, "GET", "/exercises")
    assert code == 401
    assert result['error'] == "Expected role of COACH"
    # Create a coach to create the template and a client to assign it to
    coach_user = sign_up_user_for_testing(client, test_coach)
    assert coach_user['user'] != None
    assert coach_user['user']['role'] == 'COACH'

    # Sign in as the coach
    login_resp = login_user_for_testing(client, test_coach)
    assert login_resp['user']['id'] != None and login_resp['user']['id'] != ""

    # Create exercises
    db_session.add(Exercise(id=1, category='Lower Back', name='Deadlifts'))
    db_session.add(Exercise(id=2, category='Latisimus Dorsi', name='Pullups'))
    db_session.commit()

    result, code = request(client, "GET", "/exercises")
    
    assert code == 200
    assert result != None
    assert len(result['exercises']) == 2

def test_post_exercise(client, db_session):
    # Create a coach to create the template and a client to assign it to
    coach_user = sign_up_user_for_testing(client, test_coach)
    assert coach_user['user'] != None
    assert coach_user['user']['role'] == 'COACH'

    # Sign in as the coach
    login_resp = login_user_for_testing(client, test_coach)
    assert login_resp['user']['id'] != None and login_resp['user']['id'] != ""

    body = {
        'category': 'Back',
        'name': 'Lateral Rows'
    }
  
    result, code = request(client, "POST", "/exercise", data=body)
    assert code == 200
    assert result != None
    assert len(result['exercises']) == 1
    assert result['exercises'][0]['category'] == body['category']
    assert result['exercises'][0]['name'] == body['name']


# TRAINING LOG
def test_get_client_training_logs(client, db_session):
    # Create a coach to create the template and a client to assign it to
    coach_user = sign_up_user_for_testing(client, test_coach)
    assert coach_user['user'] != None
    assert coach_user['user']['role'] == 'COACH'
    # create a client
    client_user = sign_up_user_for_testing(client, test_client)
    assert client_user['user'] != None
    assert client_user['user']['role'] == 'CLIENT'

    # Sign in as the coach
    login_resp = login_user_for_testing(client, test_coach)
    assert login_resp['user']['id'] != None and login_resp['user']['id'] != ""

    # Create the client template, this function returns the coach_template used to assign to a client
    resp, code, coach_template = create_client_template(client, db_session, client_user['user']['id'])
    assert code == 200
    assert resp != None
    assert resp['name'] == coach_template.name and resp['user_id'] == client_user['user']['id']

    # Set one of the sessions as true and add a training entry
    client_sessions = db_session.query(ClientSession).all()
    assert client_sessions != None
    assert len(client_sessions) == 2
    client_sessions[0].completed = True
    client_sessions[0].completed_date = '2020-01-01'
    client_sessions[0].training_entries = [
        TrainingEntry(
            name='Test Exercise', category='Test Category', reps=10, sets=10, weight=150, order=1
        )
    ]
    db_session.commit()

    # Retrieve client training log and check that 1 session is included with 1 training entry
    resp, code = request(client, "GET", "/client/trainingLog?client_id={}".format(client_user['user']['id']))
    assert code == 200
    assert len(resp['sessions']) == 1
    assert len(resp['sessions'][0]['training_entries']) == 1

    # Set the second session to true to test pagination
    client_sessions[1].completed = True
    client_sessions[1].completed_date = '2020-01-02'
    db_session.commit()

    # Return paginated sessions, even though there are 2 sessions, this should only return 1
    resp, code = request(client, "GET", "/client/trainingLog?client_id={}&page=1&page_size=1".format(client_user['user']['id']))
    assert code == 200
    assert len(resp['sessions']) == 1
    assert len(resp['sessions'][0]['training_entries']) == 1

    # check error handling
    url = '/client/trainingLog'
    resp, code = request(client, 'GET', url)
    assert code == 400
    assert resp['error'] == "No query parameter client_id found in query parameter" 

# ------------------------------------- CHECKINS -------------------------------------
def test_get_checkins(client, db_session):
    # Create a coach to create the template and a client to assign it to
    coach_user = sign_up_user_for_testing(client, test_coach)
    assert coach_user['user'] != None
    assert coach_user['user']['role'] == 'COACH'

    # Create 2 clients so we can create check_ins for them
    client_user_1 = sign_up_user_for_testing(client, test_client)
    assert client_user_1['user'] != None
    assert client_user_1['user']['role'] == 'CLIENT'
    client_user_2 = sign_up_user_for_testing(client, {
        'first_name': 'test',
        'last_name': 'client',
        'email': 'test_2@client.com',
        'password': 'fakepassword',
        'role': 'CLIENT'
    })
    assert client_user_2['user'] != None
    assert client_user_2['user']['role'] == 'CLIENT'

    # Sign in as the coach
    login_resp = login_user_for_testing(client, test_coach)
    assert login_resp['user']['id'] != None and login_resp['user']['id'] != ""

    # Create a client_template for each client, 1 check in should be created per template
    resp, code, _ = create_client_template(client, db_session, client_user_1['user']['id'])
    assert code == 200
    assert resp != None
    resp, code, _ = create_client_template(client, db_session, client_user_2['user']['id'], starting_exercise_id=3)
    assert code == 200
    assert resp != None

    # Complete one of the checkins and change the end dates to be 1 day before today so they appear in the results
    check_ins = db_session.query(CheckIn).all()
    assert len(check_ins)
    check_ins[0].completed = True
    check_ins[0].end_date = (dt.today()-timedelta(days=1)).strftime(DATE_FORMAT)
    check_ins[1].end_date = (dt.today()-timedelta(days=1)).strftime(DATE_FORMAT)
    db_session.commit()

    # Retrieve the list of all check_ins for all users, each user should have 2 check ins
    resp, code = request(client, "GET", "/checkins")
    assert code == 200
    assert resp != None
    assert len(resp['completed']) == 1
    assert len(resp['uncompleted']) == 1
 

def test_get_checkin(client, db_session):
   # Create a coach to create the template and a client to assign it to
    coach_user = sign_up_user_for_testing(client, test_coach)
    assert coach_user['user'] != None
    assert coach_user['user']['role'] == 'COACH'
    # create a client
    client_user = sign_up_user_for_testing(client, test_client)
    assert client_user['user'] != None
    assert client_user['user']['role'] == 'CLIENT'

    # Sign in as the coach
    login_resp = login_user_for_testing(client, test_coach)
    assert login_resp['user']['id'] != None and login_resp['user']['id'] != ""

    # Create the client template, this function returns the coach_template used to assign to a client
    resp, code, coach_template = create_client_template(client, db_session, client_user['user']['id'])
    assert code == 200
    assert resp != None
    assert resp['name'] == coach_template.name and resp['user_id'] == client_user['user']['id']

    # Update a particular client session, we will update the first client session
    # make completed = True and add the completed_date
    session = ClientSession.query.filter_by(id=resp['sessions'][0]['id']).first()
    session.completed = True
    session.completed_date = '2020-10-08'
    db.session.commit()
    
    # retrieve a checkin
    check_in = db_session.query(CheckIn).first()  
    assert check_in != None

    # format date string
    date_split = check_in.start_date.split(' ')
    check_in.start_date = date_split[0]

    # Retrieve sessions from a particular checkin corresponding to the created client_template_id
    url = '/checkin?checkin_id={}'.format(check_in.id)
    checkin_resp, code = request(client, 'GET', url)
    session_completed_date = dt.strptime(str(checkin_resp['sessions'][0]['completed_date']), '%Y-%m-%d')
    checkin_start_date = dt.strptime(str(check_in.start_date), '%Y-%m-%d') 
    assert code == 200
    assert checkin_resp != None
    assert checkin_resp['sessions'][0]['completed'] == True
    assert session_completed_date > checkin_start_date

    logout_resp = logout_user_for_testing(client)
    assert logout_resp['success'] == True

    # Sign in as the client
    login_resp = login_user_for_testing(client, test_client)
    assert login_resp['user']['id'] != None and login_resp['user']['id'] != ""

    # Retrieve sessions from a particular checkin corresponding to the created client_template_id
    url = '/checkin?client_id={}'.format(login_resp['user']['id'])
    checkin_resp, code = request(client, 'GET', url)
    session_completed_date = dt.strptime(str(checkin_resp['sessions'][0]['completed_date']), '%Y-%m-%d')
    checkin_start_date = dt.strptime(str(check_in.start_date), '%Y-%m-%d') 
    assert code == 200
    assert checkin_resp != None
    assert checkin_resp['sessions'][0]['completed'] == True
    assert session_completed_date > checkin_start_date

    # check error handling
    url = '/checkin'
    resp, code = request(client, 'GET', url)
    assert code == 400
    assert resp['error'] == "client_id not found in query parameter, client_id must be passed when a client calls this endpoint"
    
    # test error: wrong checkin_id
    checkin_id = 100
    url = '/checkin?checkin_id={}'.format(checkin_id)
    checkin_resp, code = request(client, 'GET', url)
    assert code == 404
    assert checkin_resp['error'] == "No checkin found with the supplied parameter"

    # test error: wrong client_id
    client_id = 100
    url = '/checkin?client_id={}'.format(client_id)
    checkin_resp, code = request(client, 'GET', url)
    assert code == 404
    assert checkin_resp['error'] == "No active template found with client_id: " + str(client_id) 
    

def test_get_client_checkins(client, db_session):
    # Create a coach to create the template and a client to assign it to
    coach_user = sign_up_user_for_testing(client, test_coach)
    assert coach_user['user'] != None
    assert coach_user['user']['role'] == 'COACH'
    
    # create a client
    client_user = sign_up_user_for_testing(client, test_client)
    assert client_user['user'] != None
    assert client_user['user']['role'] == 'CLIENT'

    # Sign in as the coach
    login_resp = login_user_for_testing(client, test_coach)
    assert login_resp['user']['id'] != None and login_resp['user']['id'] != ""

    # Create the client template, this function returns the coach_template used to assign to a client
    resp, code, coach_template = create_client_template(client, db_session, client_user['user']['id'])
    assert code == 200
    assert resp != None
    assert resp['name'] == coach_template.name and resp['user_id'] == client_user['user']['id']

    # Retrieve check_ins with given client_id
    url = '/client/checkins?client_id={}'.format(client_user['user']['id'])
    checkins, code = request(client, 'GET', url)
    assert code == 200
    assert checkins != None
    # 2 checkins should have been made
    assert len(checkins) == 2
    # because the checkin.end_date will be a day from now, both arrays should be empty
    # we do not want to retrieve checkins that have not reached their end date
    assert len(checkins['completed']) == 0 and len(checkins['uncompleted']) == 0

    # check error handling
    url = '/client/checkins'
    resp, code = request(client, 'GET', url)
    assert code == 400
    assert resp['error'] == "No query parameter client_id found in request"

def test_submit_checkin(client, db_session):
    # Create a coach to create the template and a client to assign it to
    coach_user = sign_up_user_for_testing(client, test_coach)
    assert coach_user['user'] != None
    assert coach_user['user']['role'] == 'COACH'
    
    # create a client
    client_user = sign_up_user_for_testing(client, test_client)
    assert client_user['user'] != None
    assert client_user['user']['role'] == 'CLIENT'

    # Sign in as the coach
    login_resp = login_user_for_testing(client, test_coach)
    assert login_resp['user']['id'] != None and login_resp['user']['id'] != ""

    # Create the client template, this function returns the coach_template used to assign to a client
    resp, code, coach_template = create_client_template(client, db_session, client_user['user']['id'])
    assert code == 200
    assert resp != None
    assert resp['name'] == coach_template.name and resp['user_id'] == client_user['user']['id']

    # retrieve a checkin
    check_in = db_session.query(CheckIn).first()  
    assert check_in != None

    data = {
        "test": True,
        "check_in": {
            "client_comment": None,
            "client_template_id": resp['id'],
            "coach_comment": "Template completed",
            "completed": False,
            "id": check_in.id
        },
        "sessions": [
            {
                'id': resp['sessions'][0]['id'],
                'name': 'Client session name change',
                'completed': True,
                'exercises': [
                    {
                        "name": "Deadlifts",
                        "category": "Lower Back",
                        "sets": 1,
                        "reps": 1,
                        "weight": 100,
                        "order": 1
                    }
                ]
            }
        ]

    }

    resp, code = request(client, "PUT", '/submitCheckin', data=data)
    assert code == 200
    assert resp != None
    assert len(resp['sessions'][0]['exercises']) == 1
    assert resp['sessions'][0]['name'] == 'Client session name change'
    assert resp['sessions'][0]['completed'] == True
    assert resp['sessions'][0]['completed_date'] == (date.today() + timedelta(days=resp['sessions'][0]['order'])).strftime(DATE_FORMAT)
    assert resp['check_in']['coach_comment'] == "Template completed"

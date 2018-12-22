""" Main UI application for using looper """

from functools import wraps
import os
import shutil
import tempfile
from flask import Blueprint, Flask, render_template, redirect, url_for, request, jsonify, session
import psutil
import peppy
import yaml
import warnings
from helpers import *
from _version import __version__

app = Flask(__name__)

CONFIG_ENV_VAR = "CARAVEL"
CONFIG_PRJ_KEY = "projects"
TOKEN_LEN = 15


@app.context_processor
def inject_dict_for_all_templates():
    return dict(version=__version__)


def clear_session_data(keys):
    """
    Removes the non default data (created in the app lifetime) from the flask.session object.
    :param keys: a list of keys to be removed from the session
    """
    if not coll_like(keys):
        raise TypeError("Keys to clear must be collection-like; "
                        "got {}".format(type(keys)))
    for key in keys:
        try:
            session.pop(key, None)
        except KeyError:
            eprint("{k} not found in the session".format(k=key))


def generate_token(n=TOKEN_LEN):
    """
    Set the global app variable login_token to the generated random string of length n.
    Print info to the terminal
    :param n: length of the token
    :return: flask.render_template
    """
    global login_token
    login_token = random_string(n)
    eprint("\n\nCaravel is protected with a token.\nCopy this link to your browser to authenticate:\n")
    geprint("http://localhost:5000/?token=" + login_token + "\n")


def token_required(func):
    """
    Used for authentication
    :param callable func: function to be decorated
    :return callable: decorated function
    """
    @wraps(func)
    def decorated(*args, **kwargs):
        global login_token
        if not app.config["DEBUG"]:
            url_token = request.args.get('token')
            if url_token is not None:
                    eprint("Using token from the URL argument")
                    try:
                        if url_token == login_token:
                            session["token"] = url_token
                        else:
                            return render_error_msg("Invalid token")
                    except KeyError:
                        return render_error_msg("No token in session")
            else:
                try:
                    session["token"]
                except KeyError:
                    try:
                        login_token
                    except NameError:
                        return render_error_msg("No login token and session token found.")
                    else:
                        return render_error_msg("Other instance of caravel is running elsewhere."
                                                " Log in using the URL printed to the terminal when it was started.")
                else:
                    eprint("Using the token from the session")
                    if session["token"] != login_token:
                        return render_error_msg("Invalid token")

        return func(*args, **kwargs)
    return decorated


@token_required
def shutdown_server():
    shut_func = request.environ.get('werkzeug.server.shutdown')
    if shut_func is None:
        raise RuntimeError('Not running with the Werkzeug Server')
    eprint("Shutting down...")
    clear_session_data(keys=['token', '_csrf_token'])
    shut_func()


def generate_csrf_token(n=100):
    """
    Generate a CSRF token
    :param n: length of a token
    :return: flask.session with "_csrf_token_key"
    """
    if '_csrf_token' not in session:
        session['_csrf_token'] = random_string(n)
    else: 
        eprint("CSRF token retrieved from the session")
    return session['_csrf_token']


app.jinja_env.globals['csrf_token'] = generate_csrf_token


# Routes
@app.errorhandler(Exception)
def unhandled_exception(e):
    clear_session_data(keys=['token', '_csrf_token'])
    app.logger.error('Unhandled Exception: %s', (e))
    return render_template('error.html', e=e), 500


@app.route('/shutdown', methods=['GET'])
@token_required
def shutdown():
    shutdown_server()
    return 'Server shutting down...'


@app.before_request
def csrf_protect():
    if request.method == "POST":
        token_csrf = session['_csrf_token']
        token_get_csrf = request.form.get("_csrf_token")
        if not token_csrf or token_csrf != token_get_csrf:
            msg = "The CSRF token is invalid"
            print(msg)
            return render_template('error.html', e=[msg])


@app.route("/")
@token_required
def index():
    project_list_path = app.config.get("project_configs") or os.getenv(CONFIG_ENV_VAR)
    if project_list_path is None:
        msg = "Please set the environment variable {} or provide a YAML file " \
              "listing paths to project config files".format(CONFIG_ENV_VAR)
        print(msg)
        return render_template('error.html', e=[msg])

    project_list_path = os.path.expanduser(project_list_path)

    if not os.path.isfile(project_list_path):
        msg = "Project configs list isn't a file: {}".format(project_list_path)
        print(msg)
        return render_template('error.html', e=[msg])

    with open(project_list_path, 'r') as stream:
        pl = yaml.safe_load(stream)
        assert CONFIG_PRJ_KEY in pl, \
            "'{}' key not in the projects list file.".format(CONFIG_PRJ_KEY)
        projects = pl[CONFIG_PRJ_KEY]
        # get all globs and return unnested list
        projects = flatten([glob_if_exists(os.path.expanduser(os.path.expandvars(prj))) for prj in projects])
    return render_template('index.html', projects=projects)


@app.route("/process", methods=['GET', 'POST'])
@token_required
def process():
    global p
    global config_file
    global p_info
    global selected_subproject
    selected_project = request.form.get('select_project')

    config_file = os.path.expandvars(os.path.expanduser(selected_project))
    p = peppy.Project(config_file)

    try:
        subprojects = list(p.subprojects.keys())
    except AttributeError:
        subprojects = None

    try:
        selected_subproject = request.form['subprojects']
        if selected_project is None:
            p = peppy.Project(config_file)
        else:
            p.activate_subproject(selected_subproject)
    except KeyError:
        selected_subproject = None

    p_info = {
        "name": p.name,
        "config_file": p.config_file,
        "sample_count": p.num_samples,
        "summary_html": "{project_name}_summary.html".format(project_name=p.name),
        "output_dir": p.metadata.output_dir,
        "subprojects": subprojects
    }

    return render_template('process.html', p_info=p_info)


@app.route('/_background_subproject')
def background_subproject():
    global p
    global config_file
    sp = request.args.get('sp', type=str)
    if sp == "reset":
        output = "No subproject activated"
        p = peppy.Project(config_file)
        sps = p.num_samples
    else:
        output = "Activated suproject: " + sp
        p.activate_subproject(sp)
        sps = p.num_samples
    return jsonify(subproj_txt=output, sample_count=sps)


@app.route('/_background_options')
def background_options():
    global p_info
    global selected_subproject
    global act
    from looper_parser import get_long_optnames
    options = get_long_optnames(parser)
    """
    options = {
        "run": ["--ignore-flags", "--allow-duplicate-names", "--compute", "--env", "--limit", "--lump", "--lumpn",
                "--file-checks", "--dry-run", "--exclude-protocols", "--include-protocols", "--sp"],
        "check": ["--all-folders", "--file-checks", "--dry-run", "--exclude-protocols", "--include-protocols", "--sp"],
        "destroy": ["--file-checks", "--force-yes", "--dry-run", "--exclude-protocols", "--include-protocols", "--sp"],
        "summarize": ["--file-checks", "--dry-run", "--exclude-protocols", "--include-protocols", "--sp"]
    }
    """
    act = request.args.get('act', type=str) or "run"
    options_act = options[act]
    return jsonify(options=render_template('options.html', options=options_act))


@app.route('/_background_summary')
def background_summary():
    global p_info
    summary_location = "{output_dir}/{summary_html}".format(output_dir=p_info["output_dir"],
                                                            summary_html=p_info["summary_html"])
    if os.path.isfile(summary_location):
        psummary = Blueprint(p.name, __name__, template_folder=p_info["output_dir"])
        @psummary.route("/{pname}/summary/<path:page_name>".format(pname=p_info["name"]), methods=['GET'])
        def render_static(page_name):
            return render_template('%s' % page_name)

        try:
            app.register_blueprint(psummary)
        except AssertionError:
            eprint("this blueprint was already registered")
        summary_string = "{name}/summary/{summary_html}".format(name=p_info["name"],
                                                                summary_html=p_info["summary_html"])
    else:
        summary_string = "Summary not available"
    return jsonify(summary=render_template('summary.html', summary=summary_string, file_name=p_info["summary_html"]))


@app.route("/action", methods=['GET', 'POST'])
@token_required
def action():
    global act
    # To be changed in future version. Looper will be imported and run within Caravel
    opt = list(set(request.form.getlist('opt')))
    eprint("\nSelected flags:\n " + '\n'.join(opt))
    eprint("\nSelected action: " + act)
    cmd = "looper " + act + " " + ' '.join(opt) + " " + config_file
    eprint("\nCreated Command: " + cmd)
    tmpdirname = tempfile.mkdtemp("tmpdir")
    eprint("\nCreated temporary directory: " + tmpdirname)
    file_run = open(tmpdirname + "/output.txt", "w")
    proc_run = psutil.Popen(cmd, shell=True, stdout=file_run)
    proc_run.wait()
    with open(tmpdirname + "/output.txt", "r") as myfile:
        output_run = myfile.readlines()
    shutil.rmtree(tmpdirname)
    return render_template("execute.html", output=output_run)


if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()
    app.config["project_configs"] = args.config
    app.config["DEBUG"] = args.debug
    app.config['SECRET_KEY'] = 'thisisthesecretkey'
    if not app.config["DEBUG"]:
        generate_token()
    else:
        warnings.warn("You have entered the debug mode. The server-client connection is not secure!")
    app.run()
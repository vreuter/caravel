
def init_globals():
    """
    This function initializes global variables, which then can be used in the whole app

    Just need to import globals and then say globs.<variable>
    """
    global summarizer
    global p
    global selected_project
    global log_path
    global act
    global compute_config
    global logging_lvl
    global summary_links
    global dests
    global reset_btn
    global command
    global currently_selected_package
    global current_subproj
    global summary_requested

    summarizer = None
    p = None
    selected_project = None
    log_path = None
    act = None
    compute_config = None
    logging_lvl = None
    summary_links = None
    dests = None
    reset_btn = None
    command = None
    currently_selected_package = None
    current_subproj = None
    summary_requested = None



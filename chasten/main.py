"""Chasten checks the AST of a Python program."""

import sys
from pathlib import Path
from typing import Any
from typing import Dict
from typing import List
from typing import Tuple
from typing import Union

import typer
import yaml
from pyastgrep import search as pyastgrepsearch  # type: ignore
from rich.panel import Panel
from rich.syntax import Syntax
from trogon import Trogon  # type: ignore
from typer.main import get_group

from chasten import configuration
from chasten import constants
from chasten import debug
from chasten import enumerations
from chasten import filesystem
from chasten import output
from chasten import process
from chasten import server
from chasten import util
from chasten import validate

# create a Typer object to support the command-line interface
cli = typer.Typer()


# ---
# Region: helper functions
# ---


def output_preamble(
    verbose: bool,
    debug_level: debug.DebugLevel = debug.DebugLevel.ERROR,
    debug_destination: debug.DebugDestination = debug.DebugDestination.CONSOLE,
    **kwargs,
) -> None:
    """Output all of the preamble content."""
    # setup the console and the logger through the output module
    output.setup(debug_level, debug_destination)
    output.logger.debug(f"Display verbose output? {verbose}")
    output.logger.debug(f"Debug level? {debug_level.value}")
    output.logger.debug(f"Debug destination? {debug_destination.value}")
    # display the header
    output.print_header()
    # display details about configuration as
    # long as verbose output was requested;
    # note that passing **kwargs to this function
    # will pass along all of the extra keyword
    # arguments that were input to the function
    output.print_diagnostics(
        verbose,
        debug_level=debug_level.value,
        debug_destination=debug_destination.value,
        **kwargs,
    )


def display_configuration_directory(
    chasten_user_config_dir_str: str, verbose: bool = False
) -> None:
    """Display information about the configuration in the console."""
    # create a visualization of the configuration directory
    chasten_user_config_dir_path = Path(chasten_user_config_dir_str)
    rich_path_tree = filesystem.create_directory_tree_visualization(
        chasten_user_config_dir_path
    )
    # display the visualization of the configuration directory
    output.opt_print_log(verbose, tree=rich_path_tree)
    output.opt_print_log(verbose, empty="")


def extract_configuration_details(
    chasten_user_config_dir_str: str,
    configuration_file: str = constants.filesystem.Main_Configuration_File,
) -> Tuple[str, str, Dict[str, Dict[str, Any]]]:
    """Display details about the configuration."""
    # display_configuration_directory(chasten_user_config_dir_str)
    # create the name of the main configuration file
    configuration_file_str = f"{chasten_user_config_dir_str}/{configuration_file}"
    # load the text of the main configuration file
    configuration_file_path = Path(configuration_file_str)
    configuration_file_yml = configuration_file_path.read_text()
    # load the contents of the main configuration file
    yaml_data = None
    with open(configuration_file_str) as user_configuration_file:
        yaml_data = yaml.safe_load(user_configuration_file)
    # return the file name, the textual contents of the configuration file, and
    # a dict-based representation of the configuration file
    return configuration_file_str, configuration_file_yml, yaml_data


def validate_file(
    configuration_file_str: str,
    configuration_file_yml: str,
    yml_data_dict: Dict[str, Dict[str, Any]],
    json_schema: Dict[str, Any] = validate.JSON_SCHEMA_CONFIG,
    verbose: bool = False,
) -> bool:
    """Validate the provided file."""
    # perform the validation of the configuration file
    (validated, errors) = validate.validate_configuration(yml_data_dict, json_schema)
    output.console.print(
        f":sparkles: Validated {configuration_file_str}? {util.get_human_readable_boolean(validated)}"
    )
    # there was a validation error, so display the error report
    if not validated:
        output.console.print(f":person_shrugging: Validation errors:\n\n{errors}")
    # validation worked correctly, so display the configuration file
    else:
        output.opt_print_log(verbose, newline="")
        output.opt_print_log(
            verbose, label=f":sparkles: Contents of {configuration_file_str}:\n"
        )
        output.opt_print_log(verbose, config_file=configuration_file_yml)
    return validated


def validate_configuration_files(
    verbose: bool = False,
) -> Tuple[bool, Union[Dict[str, Dict[str, Any]], Dict[Any, Any]]]:
    """Validate the configuration."""
    # detect and store the platform-specific user
    # configuration directory
    chasten_user_config_dir_str = configuration.user_config_dir(
        application_name=constants.chasten.Application_Name,
        application_author=constants.chasten.Application_Author,
    )
    output.console.print(
        ":sparkles: Configuration directory:"
        + constants.markers.Space
        + chasten_user_config_dir_str
        + constants.markers.Newline
    )
    # create a visualization of the user's configuration directory
    # display details about the configuration directory
    display_configuration_directory(chasten_user_config_dir_str, verbose)
    (
        configuration_file_str,
        configuration_file_yml,
        yml_data_dict,
    ) = extract_configuration_details(chasten_user_config_dir_str)
    # validate the user's configuration and display the results
    config_file_validated = validate_file(
        configuration_file_str,
        configuration_file_yml,
        yml_data_dict,
        validate.JSON_SCHEMA_CONFIG,
        verbose,
    )
    # if one or more exist, retrieve the name of the checks files
    (_, checks_file_name_list) = validate.extract_checks_file_name(yml_data_dict)
    # iteratively extract the contents of each checks file
    # and then validate the contents of that checks file
    checks_files_validated_list = []
    check_files_validated = False
    for checks_file_name in checks_file_name_list:
        (
            configuration_file_str,
            configuration_file_yml,
            yml_data_dict,
        ) = extract_configuration_details(chasten_user_config_dir_str, checks_file_name)
        # validate a checks configuration file
        check_file_validated = validate_file(
            configuration_file_str,
            configuration_file_yml,
            yml_data_dict,
            validate.JSON_SCHEMA_CHECKS,
            verbose,
        )
        # output.console.print(yml_data_dict)
        checks_files_validated_list.append(check_file_validated)
    check_files_validated = all(checks_files_validated_list)
    # the files validated correctly
    if config_file_validated and check_files_validated:
        return (True, yml_data_dict)
    # there was at least one validation error
    return (False, {})


# ---
# Region: command-line interface functions
# ---


@cli.command()
def interact(ctx: typer.Context) -> None:
    """Interactively configure and run."""
    Trogon(get_group(cli), click_context=ctx).run()


@cli.command()
def configure(
    task: enumerations.ConfigureTask = typer.Argument(
        enumerations.ConfigureTask.VALIDATE.value
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Create configuration directory and files even if they exist",
    ),
    verbose: bool = typer.Option(False),
    debug_level: debug.DebugLevel = typer.Option(debug.DebugLevel.ERROR.value),
    debug_destination: debug.DebugDestination = typer.Option(
        debug.DebugDestination.CONSOLE.value, "--debug-dest"
    ),
) -> None:
    """Manage tool configuration."""
    # output the preamble, including extra parameters specific to this function
    output_preamble(
        verbose, debug_level, debug_destination, task=task.value, force=force
    )
    # display the configuration directory and its contents
    if task == enumerations.ConfigureTask.VALIDATE:
        validate_configuration_files()
    # create the configuration directory and a starting version of the configuration file
    if task == enumerations.ConfigureTask.CREATE:
        # attempt to create the configuration directory
        try:
            created_directory_path = filesystem.create_configuration_directory(force)
            output.console.print(
                f":sparkles: Created configuration directory and file(s) in {created_directory_path}"
            )
        # cannot re-create the configuration directory, so display
        # a message and suggest the use of --force the next time
        except FileExistsError:
            if not force:
                output.console.print(
                    ":person_shrugging: Configuration directory already exists."
                )
                output.console.print(
                    "Use --force to recreate configuration directory and its containing files."
                )


@cli.command()
def analyze(  # noqa: PLR0913
    directory: List[Path] = typer.Option(
        filesystem.get_default_directory_list(),
        "--search-directory",
        "-d",
        help="One or more directories with Python code",
    ),
    check_include: list[str] = typer.Option(
        [], "--check-include", help="List of checks to include."
    ),
    check_exclude: list[str] = typer.Option(
        [], "--check-exclude", help="List of checks to exclude."
    ),
    verbose: bool = typer.Option(False),
    debug_level: debug.DebugLevel = typer.Option(debug.DebugLevel.ERROR.value),
    debug_destination: debug.DebugDestination = typer.Option(
        debug.DebugDestination.CONSOLE.value, "--debug-dest"
    ),
) -> None:
    """Analyze the AST of Python source code."""
    # output the preamble, including extra parameters specific to this function
    output_preamble(verbose, debug_level, debug_destination, directory=directory)
    # add extra space after the command to run the program
    output.console.print()
    # validate the configuration
    (validated, checks_dict) = validate_configuration_files()
    # some aspect of the configuration was not
    # valid, so exit early and signal an error
    if not validated:
        output.console.print(
            "\n:person_shrugging: Cannot perform analysis due to configuration error(s).\n"
        )
        sys.exit(constants.markers.Non_Zero_Exit)
    # extract the list of the specific patterns (i.e., the XPATH expressions)
    # that will be used to analyze all of the XML-based representations of
    # the Python source code found in the valid directories
    check_list = checks_dict["checks"]
    # collect all of the directories that are invalid
    invalid_directories = []
    for current_directory in directory:
        if not filesystem.confirm_valid_directory(current_directory):
            invalid_directories.append(current_directory)
    # create the list of valid directories by removing the invalid ones
    valid_directories = list(set(directory) - set(invalid_directories))
    # output the list of directories subject to checking
    output.console.print(
        f":sparkles: Analyzing Python source code in:\n{', '.join(str(d) for d in valid_directories)}"
    )
    # output the number of checks that will be performed
    output.console.print()
    output.console.print(f":tada: Found a total of {len(check_list)} check(s):")
    # iterate through and perform each of the checks
    for current_check in check_list:
        # extract the name of the current check and confirm that:
        # --> It is not in the exclude list
        # --> It is in the include list
        current_check_name = current_check[constants.checks.Check_Name]  # type: ignore
        # go to the next check if this one was not specified
        if (
            current_check_name in check_exclude
            or current_check_name not in check_include
        ):
            continue
        # extract the pattern for the current check
        current_xpath_pattern = current_check[constants.checks.Check_Pattern]  # type: ignore
        # display the XPATH expression for the current check
        output.console.print("\n:tada: Performing check:")
        xpath_syntax = Syntax(
            current_xpath_pattern,
            constants.markers.Xml,
            theme=constants.chasten.Theme_Colors,
        )
        # extract details about the check to display in the header
        # of the syntax box for this specific check
        check_id = current_check[constants.checks.Check_Id]  # type: ignore
        check_name = current_check[constants.checks.Check_Name]  # type: ignore
        output.console.print(
            Panel(
                xpath_syntax,
                expand=False,
                title=f"Id={check_id}, Name={check_name}",
            )
        )
        # search for the XML contents of an AST that match the provided
        # XPATH query using the search_python_file in search module of pyastgrep
        match_generator = pyastgrepsearch.search_python_files(
            paths=valid_directories,
            expression=current_xpath_pattern,
        )
        # materialize a list from the generator of (potential) matches;
        # note that this list will also contain an object that will
        # indicate that the analysis completed for each located file
        match_generator_list = list(match_generator)
        # filter the list of matches so that it only includes
        # those that are a Match object that will contain source code
        (match_generator_list, _) = process.filter_matches(
            match_generator_list, pyastgrepsearch.Match
        )
        output.console.print()
        output.console.print(
            f":sparkles: Found a total of {len(match_generator_list)} matches"
        )
        # for each potential match, log and, if verbose model is enabled,
        # display details about each of the matches
        for search_output in match_generator_list:
            if isinstance(search_output, pyastgrepsearch.Match):
                # display a label for matching output information
                output.opt_print_log(verbose, blank="")
                output.opt_print_log(verbose, label=":sparkles: Matching source code:")
                # extract the direct line number for this match
                position_end = search_output.position.lineno
                # get a pre-defined number of the lines both
                # before and after the line that is the closest match;
                # note that the use of "*" is an indicator of the
                # specific line that is the focus of the search
                all_lines = search_output.file_lines
                all_lines[
                    position_end
                ] = f"*{all_lines[position_end][constants.markers.Slice_One:]}"
                lines = all_lines[
                    position_end
                    - constants.markers.Code_Context : position_end
                    + constants.markers.Code_Context
                ]
                # create a rich panel to display the results
                code_syntax = Syntax(
                    "\n".join(str(line) for line in lines),
                    "python",
                    theme=constants.chasten.Theme_Colors,
                    background_color=constants.chasten.Theme_Background,
                )
                output.opt_print_log(
                    verbose,
                    panel=Panel(
                        code_syntax,
                        expand=False,
                        title=f"{search_output.path}:{search_output.position.lineno}:{search_output.position.col_offset}",
                    ),
                )


@cli.command()
def log() -> None:
    """Start the logging server."""
    # display the header
    output.print_header()
    # display details about the server
    output.print_server()
    # run the server; note that this
    # syslog server receives debugging
    # information from chasten.
    # It must be started in a separate process
    # before running any sub-command
    # of the chasten tool
    server.start_syslog_server()

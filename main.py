import os
import click
import configparser
from database import DatabaseConnectionPool as Database
from log_parser import LogParser, BasicLogParser, LogParserWithLookup
import applog

script_dir = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.abspath(os.path.join(script_dir,'../etc/aggregator', 'config.ini'))
log_structure_path = os.path.abspath(os.path.join(script_dir,'../etc/aggregator', 'log_structure.xml'))
applog_path = os.path.join(script_dir, '/var/log/aggregator.log')

class AppContext:
    def __init__(self):
        self.db_manager: Database = None
        self.parser: LogParser = None

    def configure_logging(self, log_file:str):
        """Configure logging to log errors to console and exceptions/warnings to file."""
        applog.set_logger(__name__, log_file)
        applog.set_logger_level('DEBUG')
        # applog.track_module('database')
        applog.track_module('log_parser')

    def load_parser(self, log_type: str):
        """Load the appropriate log parser based on log type."""

        if log_type == "extended":
            # self.parser = BasicLogParser(self.db_manager, f"{log_type}_logs")

            self.parser = LogParserWithLookup(self.db_manager, f"{log_type}_logs", ["user_groups", "request_profiles", "response_profiles", "categories", "profiles", "download_content_types", "upload_content_types", "time_profiles", "application_signatures"])

            # self.parser = LogParserLookup(self.db_manager, f"{log_type}_logs", ["method", "filter_name", "username", "status", "client_ip", "mime", "cachecode", "peercode"])

        else:
            self.parser = BasicLogParser(self.db_manager, f"{log_type}_logs")
        
        self.parser.load_log_schema(log_type, log_structure_path)

pass_context = click.make_pass_decorator(AppContext, ensure=True)

@click.group()
@pass_context
def cli(ctx: AppContext):
    """Command-line interface for managing the database and logs."""
    config = configparser.ConfigParser()
    config.read(config_path)
    username = config['database']['username']
    password = config['database']['password']
    host = config['database']['host']
    port = config['database']['port']  # Port remains as a string
    dbname = config['database']['dbname']
    maxconns = config['database']['maxconns']
    ctx.db_manager = Database(username, password, host, port, dbname, maxconns)
    ctx.db_manager.create_extension_for_timescaledb()

    ctx.configure_logging(applog_path)

@cli.command()
@pass_context
def analyse_database(ctx: AppContext):
    """Analyze logs in the database."""
    print(ctx.db_manager)  # Placeholder for actual analysis logic

@cli.command()
@click.argument('log_type', type=click.Choice(['extended', 'performance', 'csp'], case_sensitive=False), required=False)
@pass_context
def clear_database(ctx: AppContext, log_type: str):
    """Clear database and drop all tables."""
    ctx.db_manager.clear_database(log_type)

@cli.command()
@click.argument('log_type', type=click.Choice(['extended', 'performance', 'csp'], case_sensitive=False), required=True)
@pass_context
def create_database(ctx: AppContext, log_type: str):
    """
    Create database and tables for log type.
    
    log_type: Type of log to create database for. Choices are 'extended', 'csp' or 'performance'.
    """
    ctx.load_parser(log_type)
    ctx.parser.create_tables()

@cli.command()
@click.argument('log_type', type=click.Choice(['extended', 'performance', 'csp'], case_sensitive=False), default='extended')
@click.argument('path', type=click.Path(exists=True))
@click.option('--workers', type=click.IntRange(1, 100), default=10, help='Number of workers to use for insertion.')
@pass_context
def insert(ctx: AppContext, log_type: str, path: str, workers: int):
    """
    Insert log entries from a file into the database.
    
    log_type: Type of log to insert. Choices are 'extended', 'csp' or 'performance'.
    path: Path to the log file or directory containing log files.
    workers: Number of workers to use for insertion.
    """

    def check_format(path:str):
        if path.endswith('.log') or path.endswith('.log.gz'):
            return True
        else:
            return False

    # Check if path is a file or a directory
    log_files = []
    if os.path.isdir(path):
        for file in os.listdir(path):
            if check_format(file):
                log_file = os.path.join(path, file)
                log_files.append(log_file)
    elif check_format(path):
        log_files.append(path)
    else:
        print("Invalid log file format. Please provide a valid log file.")
        return

    ctx.load_parser(log_type)

    initial_size = ctx.parser.database.get_database_size()
    # print(f"Size of database before insertion: {initial_size}")

    ctx.parser.insert_log_files(log_files, workers)

    final_size = ctx.parser.database.get_database_size()

    # print(f"Size of database after insertion: {final_size}")
    print(f"Size increased: {(final_size - initial_size)//1024} KB")
    print("Logs inserted successfully.")

if __name__ == "__main__":
    cli()

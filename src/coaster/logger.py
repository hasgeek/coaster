"""
Exception logger.

Coaster can help your application log errors at run-time. Initialize with
:func:`coaster.logger.init_app`. If you use :func:`coaster.app.init_app`,
this is done automatically for you.
"""
# spell-checker:ignore typeshed apikey stripetoken cardnumber levelname
# pyright: reportMissingImports=false

from __future__ import annotations

import logging
import logging.handlers
import re
import sys
import textwrap
import traceback
import types
import warnings
from collections.abc import MutableSet
from datetime import datetime, timedelta
from email.utils import formataddr
from html import escape
from inspect import isawaitable
from io import StringIO
from pprint import pprint
from threading import Lock, Thread
from typing import IO, TYPE_CHECKING, Any, Optional, Union, cast

from werkzeug.datastructures import MultiDict

if TYPE_CHECKING:
    # This type definition is only available in the typeshed stub
    from logging import _SysExcInfoType

import requests
from flask.config import Config  # Quart's config subclasses Flask's

from .auth import current_auth
from .compat import BaseApp, g, request, session, sync_await

# Regex for credit card numbers
_card_re = re.compile(r'\b(?:\d[ -]*?){13,16}\b')

# These keywords are borrowed from Sentry's documentation and expanded for PII
_filter_re = re.compile(
    '''
    (password
    |secret
    |passwd
    |api_key
    |apikey
    |access_token
    |auth_token
    |_token
    |token_
    |credentials
    |mysql_pwd
    |stripetoken
    |cardnumber
    |email
    |phone)
    ''',
    re.IGNORECASE | re.VERBOSE,
)

# Don't allow init on the same logger twice
log_init_cache: MutableSet[Optional[str]] = set()


class ConfigWarning(UserWarning):
    """Warning for deprecated config keys."""


class FilteredValueIndicator:
    """Represent a filtered value."""

    def __str__(self) -> str:
        """Filter str."""
        return '[Filtered]'

    def __repr__(self) -> str:
        """Filter repr."""
        return '[Filtered]'


# Construct a singleton
filtered_value_indicator = FilteredValueIndicator()


class RepeatValueIndicator:
    """Represent a repeating value."""

    def __init__(self, key: str) -> None:
        """Init with key."""
        self.key = key

    def __repr__(self) -> str:
        """Return representation."""
        return f'<same as prior {self.key!r}>'

    __str__ = __repr__


def filtered_value(key: Any, value: Any) -> Any:
    """Find and mask sensitive values based on key names."""
    if isinstance(key, str) and _filter_re.search(key):
        return filtered_value_indicator
    if isinstance(value, str):
        return _card_re.sub('[Filtered]', value)
    return value


def pprint_with_indent(dictlike: dict, outfile: IO, indent: int = 4) -> None:
    """Filter values and pprint with indent to create a Markdown code block."""
    out = StringIO()
    pprint(  # noqa: T203
        {key: filtered_value(key, value) for key, value in dictlike.items()}, out
    )
    outfile.write(textwrap.indent(out.getvalue(), ' ' * indent))
    out.close()


STACK_FRAMES_NOTICE = "Stack frames (most recent call first):"


class LocalVarFormatter(logging.Formatter):
    """Log the contents of local variables in the stack frame."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Init formatter."""
        super().__init__(*args, **kwargs)
        self.lock = Lock()

    def format(self, record: logging.LogRecord) -> str:
        """
        Format the specified record as text.

        Overrides :meth:`logging.Formatter.format` to remove cache of
        :attr:`record.exc_text` unless it was produced by this formatter.
        """
        if (
            record.exc_info
            and record.exc_text
            and STACK_FRAMES_NOTICE not in record.exc_text
        ):
            record.exc_text = None
        return super().format(record)

    def formatException(self, ei: _SysExcInfoType) -> str:  # noqa: N802
        """Render a stack trace with local variables in each stack frame."""
        tb = ei[2]
        if tb is None:
            return ''
        while True:
            if not tb.tb_next:
                break
            tb = tb.tb_next
        stack = []
        f: Optional[types.FrameType] = tb.tb_frame
        while f:
            stack.append(f)
            f = f.f_back

        sio = StringIO()
        traceback.print_exception(ei[0], ei[1], ei[2], None, sio)

        with self.lock:
            # Monkey-patch Flask Config's __repr__ to not dump sensitive config. This
            # can happen when a Jinja2 template is part of the stack, as templates get
            # app config. We perform this patch and dump within a lock to ensure no
            # conflict with a parallel stack dump -- which could otherwise restore the
            # original __repr__ while this is still dumping.
            original_config_repr = Config.__repr__
            Config.__repr__ = (  # type: ignore[method-assign]
                lambda self: '<Config [FILTERED]>'  # noqa: ARG005
            )
            value_cache: dict[Any, str] = {}

            print('\n----------\n', file=sio)
            print(STACK_FRAMES_NOTICE, file=sio)
            for frame in stack:
                print('\n----\n', file=sio)
                print(
                    f"Frame {frame.f_code.co_name} in {frame.f_code.co_filename} at"
                    f" line {frame.f_lineno}",
                    file=sio,
                )
                for attr, value in list(frame.f_locals.items()):
                    idvalue = id(value)
                    if idvalue in value_cache:
                        value = RepeatValueIndicator(value_cache[idvalue])
                    else:
                        value_cache[idvalue] = f"{frame.f_code.co_name}.{attr}"
                    print(f"\t{attr:>20} = ", end=' ', file=sio)
                    try:
                        print(repr(filtered_value(attr, value)), file=sio)
                    except Exception:  # noqa: BLE001  # pylint: disable=broad-except
                        # We need a bare except clause because this is the exception
                        # handler. It can't have exceptions of its own.
                        print("<ERROR WHILE PRINTING VALUE>", file=sio)

            del value_cache
            Config.__repr__ = original_config_repr  # type: ignore[method-assign]

        if request:
            print('\n----------\n', file=sio)
            print("Request context:", file=sio)
            request_form: MultiDict
            request_form = request.form  # type: ignore[assignment]
            if isawaitable(request_form):
                request_form = sync_await(request_form)
            request_data = {
                'form': {
                    k: filtered_value(k, v)
                    for k, v in request_form.to_dict(flat=False).items()
                },
                'args': {
                    k: filtered_value(k, v)
                    for k, v in request.args.to_dict(flat=False).items()
                },
                'headers': request.headers,
                'environ': getattr(request, 'environ', None),
                'method': request.method,
                'blueprint': request.blueprint,
                'endpoint': request.endpoint,
                'view_args': request.view_args,
            }
            try:
                pprint_with_indent(request_data, sio)
            except Exception:  # noqa: BLE001  # pylint: disable=broad-except
                print("<ERROR WHILE PRINTING VALUE>", file=sio)

        if session:
            print('\n----------\n', file=sio)
            print("Session cookie contents:", file=sio)
            try:
                pprint_with_indent(dict(session), sio)
            except Exception:  # noqa: BLE001  # pylint: disable=broad-except
                print("<ERROR WHILE PRINTING VALUE>", file=sio)

        if g:
            print('\n----------\n', file=sio)
            print("App context:", file=sio)
            try:
                pprint_with_indent(vars(g), sio)
            except Exception:  # noqa: BLE001  # pylint: disable=broad-except
                print("<ERROR WHILE PRINTING VALUE>", file=sio)

        if current_auth:
            print('\n----------\n', file=sio)
            print("Current auth:", file=sio)
            try:
                pprint_with_indent(vars(current_auth), sio)
            except Exception:  # noqa: BLE001  # pylint: disable=broad-except
                print("<ERROR WHILE PRINTING VALUE>", file=sio)

        s = sio.getvalue()
        sio.close()
        if s[-1:] == '\n':
            s = s[:-1]
        return s


class EmailHandler(logging.handlers.SMTPHandler):
    """SMTPHandler with a subject formatter."""

    def getSubject(self, record: logging.LogRecord) -> str:  # noqa: N802
        """Provide error information in the email subject."""
        # Reuses SMTPHandler's 'subject' attr to store the app name
        return f'{record.levelname} in {self.subject}: {record.message}'


class SlackHandler(logging.Handler):
    """Custom logging handler to post error reports to Slack."""

    def __init__(self, app_name: str, webhooks: list[dict[str, Any]]) -> None:
        """Init handler."""
        super().__init__()
        self.app_name = app_name
        self.webhooks = webhooks
        self.throttle_lock = Lock()
        self.throttle_cache: dict[tuple[str, int], datetime] = {}

    def emit(self, record: logging.LogRecord) -> None:
        """Emit an event."""
        try:
            throttle_key = (record.module, record.lineno)
            with self.throttle_lock:
                if throttle_key in self.throttle_cache and (
                    (datetime.now() - self.throttle_cache[throttle_key])
                    < timedelta(minutes=5)
                ):
                    return
            # Sanity check: If we're not going to be reporting this, don't bother
            # to format payload
            if record.levelname not in [
                lname
                for webhook in self.webhooks
                for lname in webhook.get('levelnames', [])
            ]:
                return
            if record.exc_text:
                double_split = [
                    s.split('----') for s in record.exc_text.split('----------')
                ]
                flat_list = [item for sublist in double_split for item in sublist]
                # Separate out the first line of each section. It'll be used as the
                # "pretext" while the rest will be used as a "text" attachment.
                sections = [s.strip().split('\n', 1) for s in flat_list]
            else:
                sections = []

            data = {
                # pylint: disable=consider-using-f-string
                'text': "*{levelname}* in {name}: {message}: `{info}`".format(
                    levelname=record.levelname,
                    name=self.app_name,
                    message=record.message,
                    info=repr(record.exc_info[1]) if record.exc_info else '',
                ),
                'attachments': [
                    {
                        'mrkdwn_in': ['text'],
                        'fallback': section[0],
                        'pretext': section[0],
                        'text': (
                            ('```\n' + section[1] + '\n```') if len(section) > 1 else ''
                        ),
                    }
                    for section in sections
                ],
            }

            for webhook in self.webhooks:
                if record.levelname not in webhook.get('levelnames', []):
                    continue
                payload = dict(data)
                for attr in ('channel', 'username', 'icon_emoji'):
                    if attr in webhook:
                        payload[attr] = webhook[attr]

                Thread(
                    target=requests.post,
                    args=[webhook['url']],
                    kwargs={
                        'json': payload,
                        'headers': {'Content-Type': 'application/json'},
                        'timeout': 30,
                    },
                    daemon=True,
                ).start()
            with self.throttle_lock:
                self.throttle_cache[throttle_key] = datetime.now()
        except Exception:  # noqa: BLE001  # pylint: disable=broad-except
            self.handleError(record)


class TelegramHandler(logging.Handler):
    """Custom logging handler to report errors to a Telegram chat."""

    def __init__(
        self, app_name: str, chatid: str, apikey: str, threadid: Optional[str] = None
    ) -> None:
        """Init handler."""
        super().__init__()
        self.app_name = app_name
        self.chatid = chatid
        self.apikey = apikey
        self.threadid = threadid
        self.throttle_lock = Lock()
        self.throttle_cache: dict[tuple[str, int], datetime] = {}

    def emit(self, record: logging.LogRecord) -> None:
        """Emit an event."""
        try:
            throttle_key = (record.module, record.lineno)
            with self.throttle_lock:
                if throttle_key in self.throttle_cache and (
                    (datetime.now() - self.throttle_cache[throttle_key])
                    < timedelta(minutes=5)
                ):
                    return
            text = (
                f'<b>{escape(record.levelname, False)}</b>'
                f' in <b>{escape(self.app_name, False)}</b>:'
                f' {escape(record.message, False)}'
            )
            if record.exc_info:
                # Reverse the traceback, after dropping the first line with
                # "Traceback (most recent call first)".
                traceback_lines = traceback.format_exception(*record.exc_info)[1:][::-1]
                for index, stack_frame in enumerate(traceback_lines):
                    stack_frame_lines = stack_frame.split('\n', 1)
                    traceback_lines[index] = (
                        '\n'.join(
                            [escape(stack_frame_lines[0].strip(), False)]
                            + [
                                '<pre>' + escape(_l.strip(), False) + '</pre>'
                                for _l in stack_frame_lines[1:]
                                if _l
                            ]
                        )
                        + '\n'
                    )
                text += '\n\n' + '\n'.join(traceback_lines)
            if len(text) > 4096:
                text = text[: 4096 - 7]  # 7 = len('</pre>…')
                if text.count('<pre>') > text.count('</pre>'):
                    text += '</pre>'
                text += '…'

            telegram_post_data = {
                'chat_id': self.chatid,
                'parse_mode': 'html',
                'text': text,
                'disable_preview': True,
            }
            if self.threadid:
                telegram_post_data['message_thread_id'] = self.threadid
            Thread(
                target=requests.post,
                args=[f'https://api.telegram.org/bot{self.apikey}/sendMessage'],
                kwargs={'data': telegram_post_data, 'timeout': 30},
                daemon=True,
            ).start()
            with self.throttle_lock:
                self.throttle_cache[throttle_key] = datetime.now()
        except Exception:  # noqa: BLE001  # pylint: disable=broad-except
            self.handleError(record)


# Config names have been standardized. Old names continue to be supported but will raise
# a warning
log_legacy_confignames = {
    'LOGFILE': 'LOG_FILE',
    'LOGFILE_LEVEL': 'LOG_FILE_LEVEL',
    'ADMINS': 'LOG_EMAIL_TO',
    'SLACK_LOGGING_WEBHOOKS': 'LOG_SLACK_WEBHOOKS',
    'TELEGRAM_ERROR_CHATID': 'LOG_TELEGRAM_CHATID',
    'TELEGRAM_ERROR_APIKEY': 'LOG_TELEGRAM_APIKEY',
}


def init_app(app: BaseApp, _warning_stacklevel: int = 2) -> None:
    """
    Enable logging for an app using :class:`LocalVarFormatter`.

    Logging handlers are enabled based on these app config values. All are optional:

    * ``LOG_FILE``: File to log to (default `None` disables logging to a file)
    * ``LOG_FILE_LEVEL``: Logging level to use for file logger (default
        :attr:`logging.WARNING`)
    * ``LOG_FILE_DELAY``: Delay opening the log file until the first log is emitted
        (default `True`)
    * ``LOG_FILE_ROTATE``: Used timed log rotation (default `True`)
    * ``LOG_FILE_ROTATE_WHEN``: When to rotate (default ``'midnight'``)
    * ``LOG_FILE_ROTATE_COUNT``: Count of old files to keep (default 7)
    * ``LOG_FILE_ROTATE_UTC``: If rotating at midnight, use UTC time (default `False`)
    * ``LOG_EMAIL_TO``: List of email addresses to mail error reports to
    * ``LOG_EMAIL_FROM``: From address of emails, defaulting to ``MAIL_DEFAULT_SENDER``
    * ``MAIL_SERVER``: SMTP server to send with (default ``localhost``)
    * ``MAIL_USERNAME`` and ``MAIL_PASSWORD``: SMTP credentials, if required
    * ``LOG_TELEGRAM_CHATID`` and ``LOG_TELEGRAM_APIKEY``: If present, will use the
        specified API key to post a message to the specified chat. If
        ``LOG_TELEGRAM_THREADID`` is present, the message will be sent to the
        specified topic thread. ``LOG_TELEGRAM_LEVEL`` may optionally specify the
        logging level, default :attr:`logging.WARNING`.
    * ``LOG_SLACK_WEBHOOKS``: If present, will send error logs to all specified
        Slack webhooks

    Format for ``LOG_SLACK_WEBHOOKS``::

        LOG_SLACK_WEBHOOKS = [
            {
                'levelnames': ['WARNING', 'ERROR', 'CRITICAL'],
                'url': 'https://hooks.slack.com/...',
            },
            ...,
        ]

    """
    # --- Prevent dupe init
    if app.name in log_init_cache:
        warnings.warn(
            f"App `{app.name}` has already been configured for logging and will not be"
            f" reconfigured. For a second app, set `app.name` to a distinct value",
            category=ConfigWarning,
            stacklevel=_warning_stacklevel,
        )
        return
    log_init_cache.add(app.name)
    logger = app.logger  # logging.getLogger()

    formatter = LocalVarFormatter(
        '%(asctime)s - %(module)s.%(funcName)s:%(lineno)s - %(levelname)s - %(message)s'
    )

    # --- Remap config names from legacy names
    for old_name, new_name in log_legacy_confignames.items():
        if old_name in app.config:
            if new_name in app.config:
                warnings.warn(
                    f"`app.config[{old_name!r}]` is deprecated and will be ignored in"
                    f" favour of new name `{new_name}` that is also in config",
                    category=ConfigWarning,
                    stacklevel=_warning_stacklevel,
                )
            else:
                app.config[new_name] = app.config[old_name]
                warnings.warn(
                    f"`app.config[{old_name!r}]` is deprecated. Rename to `{new_name}`"
                    f" to stop this warning",
                    category=ConfigWarning,
                    stacklevel=_warning_stacklevel,
                )

    # --- File handler (optionally rotated)
    error_log_file = app.config.get('LOG_FILE')
    if error_log_file:  # Specify a falsy value in config to disable the log file
        error_log_file_delay = app.config.get('LOG_FILE_DELAY', True)
        if app.config.get('LOG_FILE_ROTATE', True):
            file_handler: logging.Handler = logging.handlers.TimedRotatingFileHandler(
                error_log_file,
                delay=error_log_file_delay,
                when=app.config.get('LOG_FILE_ROTATE_WHEN', 'midnight'),
                interval=app.config.get('LOG_FILE_ROTATE_INTERVAL', 1),
                backupCount=app.config.get('LOG_FILE_ROTATE_COUNT', 7),
                utc=app.config.get('LOG_FILE_ROTATE_UTC', False),
            )
        else:
            if sys.platform in ('linux', 'darwin'):
                # WatchedFileHandler cannot be used on Windows. Also skip on unknown
                # platforms, falling back to a regular FileHandler
                file_handler = logging.handlers.WatchedFileHandler(
                    error_log_file, delay=error_log_file_delay
                )
            else:
                file_handler = logging.FileHandler(
                    error_log_file, delay=error_log_file_delay
                )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(app.config.get('LOG_FILE_LEVEL', logging.WARNING))
        logger.addHandler(file_handler)

    # --- Email handler
    if app.config.get('LOG_EMAIL_TO'):
        email_to: Union[str, list[str]] = app.config['LOG_EMAIL_TO']
        if isinstance(email_to, str):
            email_to = [email_to]

        # From address (string or tuple/list)
        email_from: Union[str, list[str], tuple[str, str]] = (
            app.config.get('LOG_EMAIL_FROM') or app.config['MAIL_DEFAULT_SENDER']
        )
        if isinstance(email_from, (list, tuple)):
            # formataddr is typed with a tuple, but when using config from env with a
            # JSON processor, it will always be a list. formataddr is okay with a list,
            # so we a use a cast here to pass type check.
            email_from = formataddr(cast(tuple[str, str], email_from))

        # Optional SMTP credentials
        if app.config.get('MAIL_USERNAME') and app.config.get('MAIL_PASSWORD'):
            email_credentials: Optional[tuple[str, str]] = (
                app.config['MAIL_USERNAME'],
                app.config['MAIL_PASSWORD'],
            )
        else:
            email_credentials = None
        email_server: Union[str, tuple[str, int]]
        email_server = str(app.config.get('MAIL_SERVER', 'localhost'))
        if 'MAIL_PORT' in app.config:
            email_server = (email_server, int(app.config['MAIL_PORT']))

        # Optional TLS settings, converted to a form SMTPHandler understands
        email_secure: Optional[Union[tuple[()], tuple[str], tuple[str, str]]] = None
        if email_credentials and app.config.get('MAIL_USE_TLS'):
            email_secure = ()  # Empty tuple to enable TLS
        elif 'MAIL_SSL_KEYFILE' in app.config:
            if 'MAIL_SSL_CERTFILE' in app.config:
                email_secure = (
                    app.config['MAIL_SSL_KEYFILE'],
                    app.config['MAIL_SSL_CERTFILE'],
                )
            else:
                email_secure = (app.config['MAIL_SSL_KEYFILE'],)

        email_handler = EmailHandler(
            mailhost=email_server,
            fromaddr=email_from,
            toaddrs=email_to,
            subject=app.name,  # EmailHandler.getSubject uses this
            credentials=email_credentials,
            secure=email_secure,
        )
        email_handler.setFormatter(formatter)
        email_handler.setLevel(logging.ERROR)
        logger.addHandler(email_handler)

    # --- Telegram handler
    if app.config.get('LOG_TELEGRAM_CHATID') and app.config.get('LOG_TELEGRAM_APIKEY'):
        telegram_handler = TelegramHandler(
            app_name=app.name,
            chatid=app.config['LOG_TELEGRAM_CHATID'],
            apikey=app.config['LOG_TELEGRAM_APIKEY'],
            threadid=app.config.get('LOG_TELEGRAM_THREADID'),
        )
        telegram_handler.setLevel(app.config.get('LOG_TELEGRAM_LEVEL', logging.WARNING))
        logger.addHandler(telegram_handler)

    # --- Slack handler
    if app.config.get('LOG_SLACK_WEBHOOKS'):
        slack_handler = SlackHandler(
            app_name=app.name,
            webhooks=app.config['LOG_SLACK_WEBHOOKS'],
        )
        slack_handler.setFormatter(formatter)
        slack_handler.setLevel(logging.NOTSET)
        logger.addHandler(slack_handler)

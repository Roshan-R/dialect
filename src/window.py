# Copyright 2020 gi-lom
# Copyright 2020-2021 Mufeed Ali
# Copyright 2020-2021 Rafael Mardojai CM
# SPDX-License-Identifier: GPL-3.0-or-later

import threading
from gettext import gettext as _
from tempfile import NamedTemporaryFile

from gi.repository import Gdk, GLib, GObject, Gtk, Gst, Handy, Pango

from gtts import gTTS, lang

from dialect.define import APP_ID, RES_PATH, MAX_LENGTH, TRANS_NUMBER
from dialect.lang_selector import DialectLangSelector
from dialect.translators import TRANSLATORS


@Gtk.Template(resource_path=f'{RES_PATH}/window.ui')
class DialectWindow(Handy.ApplicationWindow):
    __gtype_name__ = 'DialectWindow'

    # Get widgets
    main_stack = Gtk.Template.Child()
    error_message = Gtk.Template.Child()
    translator_box = Gtk.Template.Child()
    retry_backend_btn = Gtk.Template.Child()

    title_stack = Gtk.Template.Child()
    langs_button_box = Gtk.Template.Child()
    switch_btn = Gtk.Template.Child()
    src_lang_btn = Gtk.Template.Child()
    src_lang_label = Gtk.Template.Child()
    dest_lang_btn = Gtk.Template.Child()
    dest_lang_label = Gtk.Template.Child()

    return_btn = Gtk.Template.Child()
    forward_btn = Gtk.Template.Child()

    menu_btn = Gtk.Template.Child()

    pronunciation_revealer = Gtk.Template.Child()
    pronunciation_label = Gtk.Template.Child()
    mistakes = Gtk.Template.Child()
    mistakes_label = Gtk.Template.Child()
    char_counter = Gtk.Template.Child()
    src_text = Gtk.Template.Child()
    clear_btn = Gtk.Template.Child()
    paste_btn = Gtk.Template.Child()
    translate_btn = Gtk.Template.Child()

    dest_box = Gtk.Template.Child()
    dest_text = Gtk.Template.Child()
    trans_spinner = Gtk.Template.Child()
    trans_warning = Gtk.Template.Child()
    copy_btn = Gtk.Template.Child()
    voice_btn = Gtk.Template.Child()

    actionbar = Gtk.Template.Child()
    src_lang_btn2 = Gtk.Template.Child()
    switch_btn2 = Gtk.Template.Child()
    dest_lang_btn2 = Gtk.Template.Child()

    notification_revealer = Gtk.Template.Child()
    notification_label = Gtk.Template.Child()

    # Translator
    translator = None
    # Language values
    lang_speech = None
    src_langs = []
    dest_langs = []
    # Current input Text
    current_input_text = ''
    current_history = 0
    no_retranslate = False
    type_time = 0
    trans_queue = []
    active_thread = None
    # These are for being able to go backspace
    first_key = 0
    second_key = 0
    mobile_mode = False
    # Connectivity issues monitoring
    trans_failed = False
    voice_loading = False
    # Trans mistakes
    trans_mistakes = None
    # Pronunciations
    trans_pronunciation = None

    # Propeties
    backend_loading = GObject.Property(type=bool, default=False)

    def __init__(self, text, settings, **kwargs):
        super().__init__(**kwargs)

        # Text passed to command line
        self.launch_text = text

        # GSettings object
        self.settings = settings
        # Application object
        self.app = kwargs['application']

        # GStreamer playbin object and related setup
        self.player = Gst.ElementFactory.make('playbin', 'player')
        bus = self.player.get_bus()
        bus.add_signal_watch()
        bus.connect('message', self.on_gst_message)
        self.player_event = threading.Event()  # An event for letting us know when Gst is done playing

        # Clipboard
        self.clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)  # This is only for the Clipboard button

        # Setup window
        self.setup()

    def setup(self):
        self.set_default_icon_name(APP_ID)

        # Load saved dark mode
        gtk_settings = Gtk.Settings.get_default()
        dark_mode = self.settings.get_boolean('dark-mode')
        gtk_settings.set_property('gtk-application-prefer-dark-theme',
                                  dark_mode)

        # Load Font
        self.src_text.override_font(Pango.FontDescription(
                                    self.settings.get_string('font-name')))

        self.dest_text.override_font(Pango.FontDescription(
                                    self.settings.get_string('font-name')))

        # Connect responsive design function
        self.connect('check-resize', self.responsive_listener)
        self.connect('destroy', self.save_translator_settings)
        self.connect('destroy', self.save_font_settings)


        self.setup_headerbar()
        self.setup_actionbar()
        self.setup_translation()
        self.toggle_mobile_mode()

        # Load translator
        self.retry_backend_btn.connect('clicked', self.retry_load_translator)
        threading.Thread(target=self.load_translator,
                         args=[self.settings.get_int('backend')],
                         daemon=True
        ).start()
        # Get languages available for speech
        threading.Thread(target=self.load_lang_speech, daemon=True).start()

    def load_translator(self, backend):
        def update_ui():
            # Supported features
            self.voice_btn.set_visible(self.translator.supported_features['voice'])

            if not self.translator.supported_features['mistakes']:
                self.mistakes.set_revealed(False)

            if not self.translator.supported_features['pronunciation']:
                self.pronunciation_revealer.set_reveal_child(False)
                self.app.pronunciation_action.set_enabled(False)

            self.no_retranslate = True
            # Update langs list
            self.src_lang_selector.set_languages(self.translator.languages)
            self.dest_lang_selector.set_languages(self.translator.languages)
            # Update selected langs
            self.src_lang_selector.set_property('selected', 'auto')
            self.dest_lang_selector.set_property('selected', self.dest_langs[0])

            self.no_retranslate = False

            self.main_stack.set_visible_child_name('translate')
            self.set_property('backend-loading', False)

        # Show loading view
        GLib.idle_add(self.main_stack.set_visible_child_name, 'loading')

        try:
            # Translator object
            if TRANSLATORS[backend].supported_features['change-instance']:
                self.translator = TRANSLATORS[backend](
                    base_url=self.settings.get_string(f'{TRANSLATORS[backend].name}-instance')
                )
            else:
                self.translator = TRANSLATORS[backend]()

            # Get saved languages
            self.src_langs = list(self.settings.get_value(f'{self.translator.name}-src-langs'))
            self.dest_langs = list(self.settings.get_value(f'{self.translator.name}-dest-langs'))

            # Update UI
            GLib.idle_add(update_ui)

        except Exception as exc:
            # Show error view
            GLib.idle_add(self.main_stack.set_visible_child_name, 'error')
            GLib.idle_add(self.set_property, 'backend-loading', False)

            self.error_message.set_label(str(exc))
            print('Error: ' + str(exc))

    def retry_load_translator(self, _button):
        threading.Thread(target=self.load_translator,
                         args=[self.settings.get_int('backend')],
                         daemon=True
        ).start()

    def on_listen_failed(self):
        self.voice_btn.set_image(self.voice_warning)
        self.voice_spinner.stop()
        self.voice_btn.set_tooltip_text(_('A network issue has occured. Retry?'))
        self.send_notification(_('A network issue has occured.\nPlease try again.'))
        dest_text = self.dest_buffer.get_text(
            self.dest_buffer.get_start_iter(),
            self.dest_buffer.get_end_iter(),
            True
        )
        if self.lang_speech:
            self.voice_btn.set_sensitive(
                self.dest_lang_selector.get_property('selected') in self.lang_speech
                and dest_text != ''
            )
        else:
            self.voice_btn.set_sensitive(dest_text != '')

    def load_lang_speech(self, listen=False, text=None, language=None):
        """
        Load the language list for gTTS.

        text and language parameters are only needed with listen parameter.
        """
        try:
            self.voice_loading = True
            self.lang_speech = list(lang.tts_langs().keys())
            if not listen:
                GLib.idle_add(self.toggle_voice_spinner, False)
            elif language in self.lang_speech and text != '':
                self.voice_download(text, language)

        except RuntimeError as exc:
            GLib.idle_add(self.on_listen_failed)
            print('Error: ' + str(exc))
        finally:
            if not listen:
                self.voice_loading = False

    def setup_headerbar(self):
        # Connect history buttons
        self.return_btn.connect('clicked', self.ui_return)
        self.forward_btn.connect('clicked', self.ui_forward)

        # Left lang selector
        self.src_lang_selector = DialectLangSelector()
        self.src_lang_selector.connect('notify::selected',
                                       self.on_src_lang_changed)
        # Set popover selector to button
        self.src_lang_btn.set_popover(self.src_lang_selector)
        self.src_lang_selector.set_relative_to(self.src_lang_btn)

        # Right lang selector
        self.dest_lang_selector = DialectLangSelector()
        self.dest_lang_selector.connect('notify::selected',
                                        self.on_dest_lang_changed)
        # Set popover selector to button
        self.dest_lang_btn.set_popover(self.dest_lang_selector)
        self.dest_lang_selector.set_relative_to(self.dest_lang_btn)

        self.langs_button_box.set_homogeneous(False)

        # Switch button
        self.switch_btn.connect('clicked', self.ui_switch)

        # Add menu to menu button
        builder = Gtk.Builder.new_from_resource(f'{RES_PATH}/menu.ui')
        menu = builder.get_object('app-menu')
        menu_popover = Gtk.Popover.new_from_model(self.menu_btn, menu)
        self.menu_btn.set_popover(menu_popover)

    def setup_actionbar(self):
        # Set popovers to lang buttons
        self.src_lang_btn2.set_popover(self.src_lang_selector)
        self.dest_lang_btn2.set_popover(self.dest_lang_selector)

        # Switch button
        self.switch_btn2.connect('clicked', self.ui_switch)

    def setup_translation(self):
        # Left buffer
        self.src_buffer = self.src_text.get_buffer()
        self.src_buffer.set_text(self.launch_text)
        self.src_buffer.connect('changed', self.on_src_text_changed)
        self.src_buffer.connect('end-user-action', self.user_action_ended)
        self.connect('key-press-event', self.update_trans_button)
        # Clear button
        self.clear_btn.connect('clicked', self.ui_clear)
        # Paste button
        self.paste_btn.connect('clicked', self.ui_paste)
        # Translate button
        self.translate_btn.connect('clicked', self.translation)
        # "Did you mean" links
        self.mistakes_label.connect('activate-link', self.on_mistakes_clicked)

        # Right buffer
        self.dest_buffer = self.dest_text.get_buffer()
        self.dest_buffer.set_text('')
        self.dest_buffer.connect('changed', self.on_dest_text_changed)
        # Clipboard button
        self.copy_btn.connect('clicked', self.ui_copy)
        # Translation progress spinner
        self.trans_spinner.hide()
        self.trans_warning.hide()
        # Voice button prep-work
        self.voice_warning = Gtk.Image.new_from_icon_name(
            'dialog-warning-symbolic', Gtk.IconSize.BUTTON)
        self.voice_btn.connect('clicked', self.ui_voice)
        self.voice_image = Gtk.Image.new_from_icon_name(
            'audio-speakers-symbolic', Gtk.IconSize.BUTTON)
        self.voice_spinner = Gtk.Spinner()  # For use while audio is running or still loading.
        self.toggle_voice_spinner(True)

    def responsive_listener(self, _window):
        size = self.get_size()

        if size.width < 600:
            if self.mobile_mode is False:
                self.mobile_mode = True
                self.toggle_mobile_mode()
        else:
            if self.mobile_mode is True:
                self.mobile_mode = False
                self.toggle_mobile_mode()

    def toggle_mobile_mode(self):
        if self.mobile_mode:
            # Show actionbar
            self.actionbar.set_reveal_child(True)
            # Change headerbar title
            self.title_stack.set_visible_child_name('label')
            # Change translation box orientation
            self.translator_box.set_orientation(Gtk.Orientation.VERTICAL)
            # Change lang selectors position
            self.src_lang_selector.set_relative_to(self.src_lang_btn2)
            self.dest_lang_selector.set_relative_to(self.dest_lang_btn2)
        else:
            # Hide actionbar
            self.actionbar.set_reveal_child(False)
            # Reset headerbar title
            self.title_stack.set_visible_child_name('selector')
            # Reset translation box orientation
            self.translator_box.set_orientation(Gtk.Orientation.HORIZONTAL)
            # Reset lang selectors position
            self.src_lang_selector.set_relative_to(self.src_lang_btn)
            self.dest_lang_selector.set_relative_to(self.dest_lang_btn)

    def translate(self, text):
        """
        Translates the given text from auto detected language to last used
        language
        """
        # Set src lang to Auto
        self.src_lang_selector.set_property('selected', 'auto')
        # Set text to src buffer
        self.src_buffer.set_text(text)
        # Run translation
        self.translation(None)

    def save_translator_settings(self, *args, **kwargs):
        if self.translator is not None:
            self.settings.set_value(f'{self.translator.name}-src-langs',
                                    GLib.Variant('as', self.src_langs))
            self.settings.set_value(f'{self.translator.name}-dest-langs',
                                    GLib.Variant('as', self.dest_langs))

    def send_notification(self, text, timeout=5):
        """
        Display an in-app notification.

        Args:
            text (str): The text or message of the notification.
            timeout (int, optional): The time before the notification disappears. Defaults to 5.
        """
        self.notification_label.set_text(text)
        self.notification_revealer.set_reveal_child(True)

        timer = threading.Timer(
            timeout,
            GLib.idle_add,
            args=[self.notification_revealer.set_reveal_child, False]
        )
        timer.start()

    def toggle_voice_spinner(self, active=True):
        if active:
            self.voice_btn.set_sensitive(False)
            self.voice_btn.set_image(self.voice_spinner)
            self.voice_spinner.start()
        else:
            dest_text = self.dest_buffer.get_text(
                self.dest_buffer.get_start_iter(),
                self.dest_buffer.get_end_iter(),
                True
            )
            self.voice_btn.set_sensitive(
                self.dest_lang_selector.get_property('selected') in self.lang_speech
                and dest_text != ''
            )
            self.voice_btn.set_image(self.voice_image)
            self.voice_spinner.stop()

    def on_src_lang_changed(self, _obj, _param):
        code = self.src_lang_selector.get_property('selected')
        dest_code = self.dest_lang_selector.get_property('selected')

        if code == dest_code:
            code = self.dest_langs[1] if code == self.src_langs[0] else dest_code
            self.dest_lang_selector.set_property('selected', self.src_langs[0])

        if code in self.translator.languages:
            self.src_lang_label.set_label(self.translator.languages[code].capitalize())
            # Updated saved left langs list
            if code in self.src_langs:
                # Bring lang to the top
                index = self.src_langs.index(code)
                self.src_langs.insert(0, self.src_langs.pop(index))
            else:
                self.src_langs.pop()
                self.src_langs.insert(0, code)
        else:
            self.src_lang_label.set_label(_('Auto'))

        # Rewrite recent langs
        self.src_lang_selector.clear_recent()
        self.src_lang_selector.insert_recent('auto', _('Auto'))
        for code in self.src_langs:
            name = self.translator.languages[code].capitalize()
            self.src_lang_selector.insert_recent(code, name)

        # Refresh list
        self.src_lang_selector.refresh_selected()

        # Translate again
        if not self.no_retranslate:
            self.translation(None)

    def on_dest_lang_changed(self, _obj, _param):
        code = self.dest_lang_selector.get_property('selected')
        src_code = self.src_lang_selector.get_property('selected')
        dest_text = self.dest_buffer.get_text(
            self.dest_buffer.get_start_iter(),
            self.dest_buffer.get_end_iter(),
            True
        )

        if code == src_code:
            code = src_code
            self.src_lang_selector.set_property('selected', self.dest_langs[0])

        # Disable or enable listen function.
        if self.lang_speech and self.translator.supported_features['voice']:
            self.voice_btn.set_sensitive(code in self.lang_speech
                                         and dest_text != '')

        name = self.translator.languages[code].capitalize()
        self.dest_lang_label.set_label(name)
        # Updated saved right langs list
        if code in self.dest_langs:
            # Bring lang to the top
            index = self.dest_langs.index(code)
            self.dest_langs.insert(0, self.dest_langs.pop(index))
        else:
            self.dest_langs.pop()
            self.dest_langs.insert(0, code)

        # Rewrite recent langs
        self.dest_lang_selector.clear_recent()
        for code in self.dest_langs:
            name = self.translator.languages[code].capitalize()
            self.dest_lang_selector.insert_recent(code, name)

        # Refresh list
        self.dest_lang_selector.refresh_selected()

        # Translate again
        if not self.no_retranslate:
            self.translation(None)

    """
    User interface functions
    """
    def ui_return(self, _button):
        """Go back one step in history."""
        if self.current_history != TRANS_NUMBER:
            self.current_history += 1
            self.history_update()

    def ui_forward(self, _button):
        """Go forward one step in history."""
        if self.current_history != 0:
            self.current_history -= 1
            self.history_update()

    def add_history_entry(self, src_language, dest_language, src_text, dest_text):
        """Add a history entry to the history list."""
        new_history_trans = {
            'Languages': [src_language, dest_language],
            'Text': [src_text, dest_text]
        }
        if self.current_history > 0:
            del self.translator.history[: self.current_history]
            self.current_history = 0
        if len(self.translator.history) > 0:
            self.return_btn.set_sensitive(True)
        if len(self.translator.history) == TRANS_NUMBER:
            self.translator.history.pop()
        self.translator.history.insert(0, new_history_trans)
        GLib.idle_add(self.reset_return_forward_btns)

    def switch_all(self, src_language, dest_language, src_text, dest_text):
        self.src_lang_selector.set_property('selected', dest_language)
        self.dest_lang_selector.set_property('selected', src_language)
        self.src_buffer.set_text(dest_text)
        self.dest_buffer.set_text(src_text)
        self.add_history_entry(src_language, dest_language, src_text, dest_text)

        # Re-enable widgets
        self.langs_button_box.set_sensitive(True)
        self.translate_btn.set_sensitive(self.src_buffer.get_char_count() != 0)

    def switch_auto_lang(self, dest_language, src_text, dest_text):
        src_language = self.translator.detect(src_text).lang
        if isinstance(src_language, list):
            src_language = src_language[0]

        # Switch all
        GLib.idle_add(self.switch_all, src_language, dest_language, src_text, dest_text)

    def ui_switch(self, _button):
        # Get variables
        self.langs_button_box.set_sensitive(False)
        self.translate_btn.set_sensitive(False)
        src_language = self.src_lang_selector.get_property('selected')
        dest_language = self.dest_lang_selector.get_property('selected')
        src_text = self.src_buffer.get_text(
            self.src_buffer.get_start_iter(),
            self.src_buffer.get_end_iter(),
            True
        )
        dest_text = self.dest_buffer.get_text(
            self.dest_buffer.get_start_iter(),
            self.dest_buffer.get_end_iter(),
            True
        )
        if src_language == 'auto':
            if src_text == '':
                src_language = self.src_langs[0]
            else:
                threading.Thread(
                    target=self.switch_auto_lang,
                    args=(dest_language, src_text, dest_text),
                    daemon=True
                ).start()
                return

        # Switch all
        self.switch_all(src_language, dest_language, src_text, dest_text)

    def ui_clear(self, _button):
        self.src_buffer.set_text('')
        self.src_buffer.emit('end-user-action')

    def ui_copy(self, _button):
        dest_text = self.dest_buffer.get_text(
            self.dest_buffer.get_start_iter(),
            self.dest_buffer.get_end_iter(),
            True
        )
        self.clipboard.set_text(dest_text, -1)
        self.clipboard.store()

    def ui_paste(self, _button):
        text = self.clipboard.wait_for_text()
        if text is not None:
            end_iter = self.src_buffer.get_end_iter()
            self.src_buffer.insert(end_iter, text)

    def ui_voice(self, _button):
        dest_text = self.dest_buffer.get_text(
            self.dest_buffer.get_start_iter(),
            self.dest_buffer.get_end_iter(),
            True
        )
        dest_language = self.dest_lang_selector.get_property('selected')
        # Add here code that changes voice button behavior
        if dest_text != '':
            self.toggle_voice_spinner(True)
            if self.lang_speech:
                threading.Thread(
                    target=self.voice_download,
                    args=(dest_text, dest_language),
                    daemon=True
                ).start()
            else:
                threading.Thread(
                    target=self.load_lang_speech,
                    args=(True, dest_text, dest_language),
                    daemon=True
                ).start()

    def on_gst_message(self, _bus, message):
        if message.type == Gst.MessageType.EOS:
            self.player.set_state(Gst.State.NULL)
            self.player_event.set()
        elif message.type == Gst.MessageType.ERROR:
            self.player.set_state(Gst.State.NULL)
            self.player_event.set()
            print('Some error occured while trying to play.')

    def voice_download(self, text, language):
        try:
            self.voice_loading = True
            tts = gTTS(text, lang=language, lang_check=False)
            with NamedTemporaryFile() as file_to_play:
                tts.write_to_fp(file_to_play)
                file_to_play.seek(0)
                self.player.set_property('uri', 'file://' + file_to_play.name)
                self.player.set_state(Gst.State.PLAYING)
                self.player_event.wait()
        except Exception as exc:
            print(exc)
            print('Audio download failed.')
            GLib.idle_add(self.on_listen_failed)
        else:
            GLib.idle_add(self.toggle_voice_spinner, False)
        finally:
            self.voice_loading = False

    # This starts the translation if Ctrl+Enter button is pressed
    def update_trans_button(self, button, keyboard):
        modifiers = keyboard.get_state() & Gtk.accelerator_get_default_mod_mask()

        control_mask = Gdk.ModifierType.CONTROL_MASK
        shift_mask = Gdk.ModifierType.SHIFT_MASK
        unicode_key_val = Gdk.keyval_to_unicode(keyboard.keyval)
        if (GLib.unichar_isgraph(chr(unicode_key_val)) and
                modifiers in (shift_mask, 0) and not self.src_text.is_focus()):
            self.src_text.grab_focus()

        if not self.settings.get_boolean('live-translation'):
            if control_mask == modifiers:
                if keyboard.keyval == Gdk.KEY_Return:
                    if not self.settings.get_value('translate-accel'):
                        self.translation(button)
                        return Gdk.EVENT_STOP
                    return Gdk.EVENT_PROPAGATE
            elif keyboard.keyval == Gdk.KEY_Return:
                if self.settings.get_value('translate-accel'):
                    self.translation(button)
                    return Gdk.EVENT_STOP
                return Gdk.EVENT_PROPAGATE

        return Gdk.EVENT_PROPAGATE

    def on_mistakes_clicked(self, _button, _data):
        self.mistakes.set_revealed(False)
        self.src_buffer.set_text(self.trans_mistakes[1])
        # Run translation again
        self.translation(None)

    def on_src_text_changed(self, buffer):
        sensitive = buffer.get_char_count() != 0
        self.translate_btn.set_sensitive(sensitive)
        self.clear_btn.set_sensitive(sensitive)

    def on_dest_text_changed(self, buffer):
        sensitive = buffer.get_char_count() != 0
        self.copy_btn.set_sensitive(sensitive)
        if not self.voice_loading and self.lang_speech:
            self.voice_btn.set_sensitive(
                self.dest_lang_selector.get_property('selected') in self.lang_speech
                and sensitive
            )
        elif not self.voice_loading and not self.lang_speech:
            self.voice_btn.set_sensitive(sensitive)

    def change_font(self, font_name):
        self.font_name = font_name
        self.src_text.override_font(Pango.FontDescription(font_name))
        self.dest_text.override_font(Pango.FontDescription(font_name))


    def save_font_settings(self, *args, **kwargs):
        if hasattr(self, 'font_name'):
            self.settings.set_value('font-name',
                                    GLib.Variant('s', self.font_name))



    def user_action_ended(self, buffer):
        # If the text is over the highest number of characters allowed, it is truncated.
        # This is done for avoiding exceeding the limit imposed by Google.
        if buffer.get_char_count() >= MAX_LENGTH:
            self.send_notification(_('5000 characters limit reached!'))
            src_text = buffer.get_text(
                buffer.get_start_iter(),
                buffer.get_end_iter(),
                True
            )
            self.src_buffer.set_text(src_text[:MAX_LENGTH])
        self.char_counter.set_text(f'{str(buffer.get_char_count())}/{MAX_LENGTH}')
        if self.settings.get_boolean('live-translation'):
            self.translation(None)

    # The history part
    def reset_return_forward_btns(self):
        self.return_btn.set_sensitive(self.current_history < len(self.translator.history) - 1)
        self.forward_btn.set_sensitive(self.current_history > 0)

    # Retrieve translation history
    def history_update(self):
        self.reset_return_forward_btns()
        lang_hist = self.translator.history[self.current_history]
        self.no_retranslate = True
        self.src_lang_selector.set_property('selected',
                                            lang_hist['Languages'][0])
        self.dest_lang_selector.set_property('selected',
                                             lang_hist['Languages'][1])
        self.no_retranslate = False
        self.src_buffer.set_text(lang_hist['Text'][0])
        self.dest_buffer.set_text(lang_hist['Text'][1])

    # THE TRANSLATION AND SAVING TO HISTORY PART
    def appeared_before(self):
        src_language = self.src_lang_selector.get_property('selected')
        dest_language = self.dest_lang_selector.get_property('selected')
        src_text = self.src_buffer.get_text(
            self.src_buffer.get_start_iter(),
            self.src_buffer.get_end_iter(),
            True
        )
        if (
            self.translator.history[self.current_history]['Languages'][0] == src_language
            and self.translator.history[self.current_history]['Languages'][1] == dest_language
            and self.translator.history[self.current_history]['Text'][0] == src_text
            and not self.trans_failed
        ):
            return True
        return False

    def translation(self, _button):
        # If it's like the last translation then it's useless to continue
        if len(self.translator.history) == 0 or not self.appeared_before():
            src_text = self.src_buffer.get_text(
                self.src_buffer.get_start_iter(),
                self.src_buffer.get_end_iter(),
                True
            )
            src_language = self.src_lang_selector.get_property('selected')
            dest_language = self.dest_lang_selector.get_property('selected')

            if self.trans_queue:
                self.trans_queue.pop(0)
            self.trans_queue.append({
                'src_text': src_text,
                'src_language': src_language,
                'dest_language': dest_language
            })

            # Check if there are any active threads.
            if self.active_thread is None:
                # Show feedback for start of translation.
                self.trans_spinner.show()
                self.trans_spinner.start()
                self.dest_box.set_sensitive(False)
                self.langs_button_box.set_sensitive(False)
                # If there is no active thread, create one and start it.
                self.active_thread = threading.Thread(target=self.run_translation, daemon=True)
                self.active_thread.start()

    def change_backends(self, backend):
        self.set_property('backend-loading', True)

        # Save previous backend settings
        self.save_translator_settings()

        # Load translator
        threading.Thread(target=self.load_translator,
                         args=[backend],
                         daemon=True
        ).start()

    def run_translation(self):
        def on_trans_failed():
            self.trans_warning.show()
            self.send_notification(_('Translation failed.\nPlease check for network issues.'))
            self.copy_btn.set_sensitive(False)
            self.voice_btn.set_sensitive(False)

        def on_trans_success():
            self.trans_warning.hide()

        def on_trans_done():
            self.trans_spinner.stop()
            self.trans_spinner.hide()
            self.dest_box.set_sensitive(True)
            self.langs_button_box.set_sensitive(True)

        def on_mistakes():
            if self.trans_mistakes is not None and self.translator.supported_features['mistakes']:
                self.mistakes_label.set_markup(_('Did you mean: ') + f'<a href="#">{self.trans_mistakes[0]}</a>')
                self.mistakes.set_revealed(True)
            elif self.mistakes.get_revealed():
                self.mistakes.set_revealed(False)

        def on_pronunciation():
            reveal = self.settings.get_boolean('show-pronunciation')
            if self.trans_pronunciation is not None and self.translator.supported_features['pronunciation']:
                self.pronunciation_label.set_text(self.trans_pronunciation)
                self.pronunciation_revealer.set_reveal_child(reveal)
            elif self.pronunciation_revealer.get_reveal_child():
                self.pronunciation_revealer.set_reveal_child(False)

        while self.trans_queue:
            # If the first language is revealed automatically, let's set it
            trans_dict = self.trans_queue.pop(0)
            src_text = trans_dict['src_text']
            src_language = trans_dict['src_language']
            dest_language = trans_dict['dest_language']
            if src_language == 'auto' and src_text != '':
                try:
                    src_language = self.translator.detect(src_text).lang
                    if isinstance(src_language, list):
                        src_language = src_language[0]
                    if src_language in self.translator.languages.keys():
                        self.no_retranslate = True
                        GLib.idle_add(self.src_lang_selector.set_property,
                                      'selected', src_language)
                        self.no_retranslate = False
                        if src_language not in self.src_langs:
                            self.src_langs[0] = src_language
                    else:
                        src_language = 'auto'
                except Exception:
                    self.trans_failed = True
            # If the two languages are the same, nothing is done
            if src_language != dest_language:
                dest_text = ''
                # THIS IS WHERE THE TRANSLATION HAPPENS. The try is necessary to circumvent a bug of the used API
                if src_text != '':
                    try:
                        translation = self.translator.translate(
                            src_text,
                            src=src_language,
                            dest=dest_language
                        )
                        dest_text = translation.text
                        self.trans_mistakes = translation.extra_data['possible-mistakes']
                        try:
                            self.trans_pronunciation = translation.extra_data['translation'][1][3]
                        except IndexError:
                            self.trans_pronunciation = None
                        self.trans_failed = False
                    except Exception as exc:
                        print(exc)
                        self.trans_mistakes = None
                        self.trans_pronunciation = None
                        self.trans_failed = True

                    # Finally, everything is saved in history
                    self.add_history_entry(
                        src_language,
                        dest_language,
                        src_text,
                        dest_text
                    )
                else:
                    self.trans_failed = False
                    self.trans_mistakes = None
                    self.trans_pronunciation = None
                GLib.idle_add(self.dest_buffer.set_text, dest_text)
                GLib.idle_add(on_mistakes)
                GLib.idle_add(on_pronunciation)

        if self.trans_failed:
            GLib.idle_add(on_trans_failed)
        else:
            GLib.idle_add(on_trans_success)
        GLib.idle_add(on_trans_done)
        self.active_thread = None

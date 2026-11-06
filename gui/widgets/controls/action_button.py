from gui.widgets.controls.primary_button import PrimaryButton
from gui.themes.theme_manager import ThemeManager
from gui.themes.styles.controls.button_style import (
    fn_primary_button_style,
    fn_secondary_button_style,
)


class ActionButton(PrimaryButton):
    def __init__(
        self,
        text="",
        width=120,
        height=40,
        variant="secondary",
        parent=None,
    ):
        self.variant = variant
        super().__init__(
            text=text,
            width=width,
            height=height,
            parent=parent,
        )

    def fn_refresh_theme(self):
        colors = ThemeManager.fn_colors()

        if self.variant == "primary":
            self.setStyleSheet(fn_primary_button_style())
            return

        if self.variant == "secondary":
            # Use a readable text color in Dark Mode
            if ThemeManager.fn_is_dark():
                self.setStyleSheet(
                    self._style(
                        colors.SECONDARY,
                        colors.SECONDARY_HOVER,
                        colors.SECONDARY_PRESSED,
                        colors.TEXT,
                    )
                )
            else:
                self.setStyleSheet(fn_secondary_button_style())
            return

        if self.variant == "stop":
            self.setStyleSheet(self._style(colors.STOP_BUTTON_BG, colors.STOP_BUTTON_HOVER,
                                           colors.STOP_BUTTON_PRESSED, colors.STOP_BUTTON_TEXT))
            return

        if self.variant == "danger":
            self.setStyleSheet(
                self._style(
                    "#FEE2E2" if not ThemeManager.fn_is_dark() else "#48282C",
                    "#FECACA" if not ThemeManager.fn_is_dark() else "#603238",
                    "#FCA5A5" if not ThemeManager.fn_is_dark() else "#783F45",
                    colors.DANGER,
                )
            )
            return

        raise ValueError(f"Unknown button variant: {self.variant}")

    @staticmethod
    def _style(background, hover, pressed, text):
        colors = ThemeManager.fn_colors()
        return f"""
            QPushButton {{
                background-color: {background};
                color: {text};
                border: 1px solid {colors.BORDER};
                border-radius: 5px;
                font-family: "Segoe UI";
                font-size: 10pt;
                font-weight: 600;
                padding: 4px 10px;
            }}

            QPushButton:hover {{
                background-color: {hover};
            }}

            QPushButton:pressed {{
                background-color: {pressed};
            }}

            QPushButton:disabled {{
                background-color: {colors.BUTTON_DISABLED};
                color: {colors.BUTTON_DISABLED_TEXT};
                border: 1px solid {colors.BUTTON_DISABLED_BORDER};
            }}
        """
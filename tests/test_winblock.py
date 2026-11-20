from usta import winblock

BERKE = (
    "DLL load failed while importing _pydantic_core: Uygulama Denetimi ilkesi bu dosyayı engelledi."
)


def test_app_control_block_is_explained_in_plain_turkish():
    msg = winblock.explain(ImportError(BERKE))
    assert msg and "_pydantic_core" in msg and "Akıllı Uygulama Denetimi" in msg
    en = "DLL load failed while importing _ctypes: An Application Control policy has blocked this file."
    assert "_ctypes" in winblock.explain(ImportError(en))


def test_other_import_errors_are_left_alone():
    assert winblock.explain(ImportError("No module named 'fastapi'")) is None
    assert (
        winblock.explain(
            ImportError(
                "DLL load failed while importing x: The specified module could not be found."
            )
        )
        is None
    )


def test_message_goes_to_the_console_when_there_is_one(capsys):
    winblock.show("deneme")
    assert "deneme" in capsys.readouterr().err

import pytest

from neo.link_previews import _OpenGraphParser, public_http_url


def test_open_graph_parser_reads_title_description_and_media():
    parser = _OpenGraphParser()
    parser.feed(
        "<html><head><title>Fallback title</title>"
        '<meta property="og:title" content="A useful page">'
        '<meta name="description" content="A short summary">'
        '<meta property="og:image" content="/cover.jpg">'
        "</head></html>"
    )

    assert parser.title == "Fallback title"
    assert parser.meta["og:title"] == "A useful page"
    assert parser.meta["description"] == "A short summary"
    assert parser.meta["og:image"] == "/cover.jpg"


@pytest.mark.asyncio
async def test_preview_validation_blocks_local_and_non_http_links():
    with pytest.raises(ValueError):
        await public_http_url("http://127.0.0.1:8000/private")
    with pytest.raises(ValueError):
        await public_http_url("file:///C:/secret.txt")

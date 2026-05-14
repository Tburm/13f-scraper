from salp_13f_monitor.cli import diff_holdings, parse_13f_xml, build_discord_payload, Filing


OLD_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <infoTable>
    <nameOfIssuer>INTEL CORP</nameOfIssuer>
    <cusip>458140100</cusip>
    <value>100</value>
    <shrsOrPrnAmt><sshPrnamt>1000</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
  </infoTable>
  <infoTable>
    <nameOfIssuer>BLOOM ENERGY CORP</nameOfIssuer>
    <cusip>093712107</cusip>
    <value>50</value>
    <shrsOrPrnAmt><sshPrnamt>500</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
  </infoTable>
</informationTable>
'''

NEW_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <infoTable>
    <nameOfIssuer>INTEL CORP</nameOfIssuer>
    <cusip>458140100</cusip>
    <value>300</value>
    <shrsOrPrnAmt><sshPrnamt>1500</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
  </infoTable>
  <infoTable>
    <nameOfIssuer>NEWCO INC</nameOfIssuer>
    <cusip>999999999</cusip>
    <value>25</value>
    <shrsOrPrnAmt><sshPrnamt>250</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
  </infoTable>
</informationTable>
'''


def test_parse_13f_xml_value_is_reported_dollars():
    holdings = parse_13f_xml(OLD_XML)
    intel = holdings["458140100|"]
    assert intel.name == "INTEL CORP"
    assert intel.value_usd == 100
    assert intel.shares == 1000


def test_diff_holdings_classifies_changes_and_signals():
    old = parse_13f_xml(OLD_XML)
    new = parse_13f_xml(NEW_XML)
    changes = diff_holdings(old, new)
    by_cusip = {c.cusip: c for c in changes}
    assert by_cusip["458140100"].kind == "increased"
    assert by_cusip["458140100"].signal == "LONG INTC"
    assert by_cusip["093712107"].kind == "sold"
    assert by_cusip["093712107"].signal == "SELL BE"
    assert by_cusip["999999999"].kind == "new"


def test_discord_payload_contains_embed():
    filing = Filing(
        accession="0002045724-26-000002",
        filing_date="2026-02-11",
        report_date="2025-12-31",
        primary_document="primary_doc.xml",
        info_table_url="https://example.com/info.xml",
        index_url="https://example.com/index.json",
    )
    changes = diff_holdings(parse_13f_xml(OLD_XML), parse_13f_xml(NEW_XML))
    payload = build_discord_payload(filing, "https://baseline.example", changes, 2, 2)
    assert payload["content"].startswith("13F update detected")
    assert payload["allowed_mentions"] == {"parse": []}
    assert payload["embeds"][0]["fields"]
    assert "Trade-style signals" in payload["embeds"][0]["fields"][-1]["name"]


def test_discord_payload_allows_here_mention():
    filing = Filing(
        accession="0002045724-26-000002",
        filing_date="2026-02-11",
        report_date="2025-12-31",
        primary_document="primary_doc.xml",
        info_table_url="https://example.com/info.xml",
        index_url="https://example.com/index.json",
    )
    payload = build_discord_payload(filing, "https://baseline.example", [], 0, 0, "@here")
    assert payload["content"].startswith("@here 13F update detected")
    assert payload["allowed_mentions"] == {"parse": ["everyone"]}

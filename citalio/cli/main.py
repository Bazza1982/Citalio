"""Citalio CLI — main entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from citalio.db.connection import get_library_root, open_and_migrate

app = typer.Typer(
    name="citalio",
    help="Citalio — standalone citation and reference management.",
    no_args_is_help=True,
)

db_app = typer.Typer(help="Database management commands.")
app.add_typer(db_app, name="db")

import_app = typer.Typer(help="[PROTOTYPE] Import references from various formats.")
app.add_typer(import_app, name="import")

export_app = typer.Typer(help="[PROTOTYPE] Export references to various formats.")
app.add_typer(export_app, name="export")

refs_app = typer.Typer(help="[PROTOTYPE] Search and inspect references.")
app.add_typer(refs_app, name="refs")

project_app = typer.Typer(help="[PROTOTYPE] Manage document projects.")
app.add_typer(project_app, name="project")

review_app = typer.Typer(help="[PROTOTYPE] Generate and apply Excel citation review sheets.")
app.add_typer(review_app, name="review")

candidates_app = typer.Typer(help="[PROTOTYPE] Manage citation candidates and decisions.")
app.add_typer(candidates_app, name="candidates")

render_app = typer.Typer(help="Render citations into documents. Step 8 (markdown) is [PROTOTYPE]. Step 9 (docx) is NOT YET AVAILABLE.")
app.add_typer(render_app, name="render")

validate_app = typer.Typer(help="[PROTOTYPE] Validate citation decisions (Step 10).")
app.add_typer(validate_app, name="validate")


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

@app.command()
def init(
    library: Optional[Path] = typer.Option(
        None,
        "--library",
        "-l",
        help="Path to the Citalio library directory (default: ~/.citalio).",
        envvar="CITALIO_HOME",
    ),
) -> None:
    """Initialise a new Citalio library and apply database migrations."""
    root = get_library_root(library)
    typer.echo(f"Initialising Citalio library at {root} ...")

    conn = open_and_migrate(library)
    conn.close()

    typer.echo(f"Library ready. Database: {root / 'citalio.db'}")


# ---------------------------------------------------------------------------
# db sub-commands
# ---------------------------------------------------------------------------

@db_app.command("status")
def db_status(
    library: Optional[Path] = typer.Option(
        None,
        "--library",
        "-l",
        envvar="CITALIO_HOME",
    ),
) -> None:
    """Show applied migration versions."""
    from citalio.db.connection import open_db

    conn = open_db(library)
    try:
        rows = conn.execute(
            "SELECT version, applied_at, description FROM schema_version ORDER BY version"
        ).fetchall()
    except Exception:
        typer.echo("schema_version table not found — run `citalio init` first.")
        raise typer.Exit(1)
    finally:
        conn.close()

    if not rows:
        typer.echo("No migrations applied yet.")
        return

    typer.echo(f"{'Version':<10} {'Applied at':<25} Description")
    typer.echo("-" * 70)
    for row in rows:
        typer.echo(f"{row['version']:<10} {row['applied_at']:<25} {row['description'] or ''}")


# ---------------------------------------------------------------------------
# import sub-commands
# ---------------------------------------------------------------------------

def _library_option() -> Optional[Path]:
    return None  # CLI-level default; individual commands declare it explicitly


@import_app.command("csl-json")
def import_csl_json_cmd(
    file: Path = typer.Option(..., "--file", "-f", help="Path to the CSL-JSON file."),
    library: Optional[Path] = typer.Option(
        None, "--library", "-l", envvar="CITALIO_HOME"
    ),
) -> None:
    """[PROTOTYPE] Import references from a CSL-JSON file."""
    from citalio.formats.csl_json import import_csl_json

    if not file.exists():
        typer.echo(f"File not found: {file}", err=True)
        raise typer.Exit(1)

    conn = open_and_migrate(library)
    try:
        count = import_csl_json(conn, file)
    finally:
        conn.close()

    typer.echo(f"Imported {count} reference(s) from {file}.")


@import_app.command("bibtex")
def import_bibtex_cmd(
    file: Path = typer.Option(..., "--file", "-f", help="Path to the .bib file."),
    library: Optional[Path] = typer.Option(
        None, "--library", "-l", envvar="CITALIO_HOME"
    ),
) -> None:
    """[PROTOTYPE] Import references from a BibTeX (.bib) file."""
    from citalio.formats.bibtex import import_bibtex

    if not file.exists():
        typer.echo(f"File not found: {file}", err=True)
        raise typer.Exit(1)

    conn = open_and_migrate(library)
    try:
        count = import_bibtex(conn, file)
    finally:
        conn.close()

    typer.echo(f"Imported {count} reference(s) from {file}.")


# ---------------------------------------------------------------------------
# export sub-commands
# ---------------------------------------------------------------------------

@export_app.command("bibtex")
def export_bibtex_cmd(
    out: Path = typer.Option(..., "--out", "-o", help="Output .bib file path."),
    ids: Optional[str] = typer.Option(
        None,
        "--ids",
        help="Comma-separated list of reference IDs to export (default: all).",
    ),
    library: Optional[Path] = typer.Option(
        None, "--library", "-l", envvar="CITALIO_HOME"
    ),
) -> None:
    """[PROTOTYPE] Export references to a BibTeX (.bib) file."""
    from citalio.formats.bibtex import export_bibtex

    reference_ids = [i.strip() for i in ids.split(",")] if ids else None
    conn = open_and_migrate(library)
    try:
        count = export_bibtex(conn, out, reference_ids=reference_ids)
    finally:
        conn.close()

    typer.echo(f"Exported {count} reference(s) to {out}.")


@export_app.command("csl-json")
def export_csl_json_cmd(
    out: Path = typer.Option(..., "--out", "-o", help="Output CSL-JSON file path."),
    ids: Optional[str] = typer.Option(
        None,
        "--ids",
        help="Comma-separated list of reference IDs to export (default: all).",
    ),
    library: Optional[Path] = typer.Option(
        None, "--library", "-l", envvar="CITALIO_HOME"
    ),
) -> None:
    """[PROTOTYPE] Export references to a CSL-JSON file."""
    from citalio.formats.csl_json import export_csl_json

    reference_ids = [i.strip() for i in ids.split(",")] if ids else None
    conn = open_and_migrate(library)
    try:
        count = export_csl_json(conn, out, reference_ids=reference_ids)
    finally:
        conn.close()

    typer.echo(f"Exported {count} reference(s) to {out}.")


# ---------------------------------------------------------------------------
# refs sub-commands
# ---------------------------------------------------------------------------

@refs_app.command("search")
def refs_search_cmd(
    query: str = typer.Argument(..., help="Search term (matched against title, abstract, citekey)."),
    limit: int = typer.Option(20, "--limit", "-n", help="Maximum number of results."),
    library: Optional[Path] = typer.Option(
        None, "--library", "-l", envvar="CITALIO_HOME"
    ),
) -> None:
    """[PROTOTYPE] Search references by title, abstract, or citekey."""
    from citalio.db.repository import CitationRepository

    conn = open_and_migrate(library)
    try:
        repo = CitationRepository(conn)
        results = repo.search_references(query, limit=limit)
    finally:
        conn.close()

    if not results:
        typer.echo("No references found.")
        return

    typer.echo(f"Found {len(results)} reference(s):\n")
    for ref in results:
        citekey_str = f" [{ref.citekey}]" if ref.citekey else ""
        year_str = f" ({ref.year})" if ref.year else ""
        typer.echo(f"  {ref.id}  {ref.title}{citekey_str}{year_str}")


@refs_app.command("show")
def refs_show_cmd(
    ref_id: str = typer.Argument(..., help="Reference UUID to display."),
    library: Optional[Path] = typer.Option(
        None, "--library", "-l", envvar="CITALIO_HOME"
    ),
) -> None:
    """[PROTOTYPE] Show full details of a single reference."""
    from citalio.db.repository import CitationRepository

    conn = open_and_migrate(library)
    try:
        repo = CitationRepository(conn)
        ref = repo.get_reference(ref_id)
    finally:
        conn.close()

    if ref is None:
        typer.echo(f"Reference not found: {ref_id}", err=True)
        raise typer.Exit(1)

    typer.echo(f"ID:        {ref.id}")
    typer.echo(f"Citekey:   {ref.citekey or '—'}")
    typer.echo(f"Type:      {ref.item_type}")
    typer.echo(f"Title:     {ref.title}")
    typer.echo(f"Year:      {ref.year or '—'}")
    typer.echo(f"DOI:       {ref.doi or '—'}")
    typer.echo(f"URL:       {ref.url or '—'}")
    if ref.publication_title:
        typer.echo(f"Published: {ref.publication_title}")
    if ref.authors:
        authors_str = "; ".join(a.display_name for a in ref.authors)
        typer.echo(f"Authors:   {authors_str}")
    if ref.editors:
        editors_str = "; ".join(e.display_name for e in ref.editors)
        typer.echo(f"Editors:   {editors_str}")
    if ref.abstract:
        short = ref.abstract[:200] + ("..." if len(ref.abstract) > 200 else "")
        typer.echo(f"Abstract:  {short}")


# ---------------------------------------------------------------------------
# project sub-commands
# ---------------------------------------------------------------------------

@project_app.command("create")
def project_create_cmd(
    name: str = typer.Option(..., "--name", "-n", help="Project name."),
    docx: Optional[Path] = typer.Option(None, "--docx", help="Path to the Word document."),
    markdown: Optional[Path] = typer.Option(None, "--markdown", "-m", help="Path to the markdown draft."),
    style: Optional[str] = typer.Option(None, "--style", help="Citation style ID."),
    library: Optional[Path] = typer.Option(None, "--library", "-l", envvar="CITALIO_HOME"),
) -> None:
    """[PROTOTYPE] Create a new document project."""
    from citalio.db.models import DocumentProjectRecord
    from citalio.db.project_repository import DocumentCitationRepository

    conn = open_and_migrate(library)
    try:
        record = DocumentProjectRecord(
            name=name,
            docx_path=str(docx) if docx else None,
            markdown_path=str(markdown) if markdown else None,
            citation_style_id=style,
        )
        repo = DocumentCitationRepository(conn)
        project_id = repo.create_project(record)
    finally:
        conn.close()

    typer.echo(f"Project created: {project_id}")
    typer.echo(f"Name:   {name}")


@project_app.command("list")
def project_list_cmd(
    library: Optional[Path] = typer.Option(None, "--library", "-l", envvar="CITALIO_HOME"),
) -> None:
    """List all document projects."""
    from citalio.db.project_repository import DocumentCitationRepository

    conn = open_and_migrate(library)
    try:
        repo = DocumentCitationRepository(conn)
        projects = repo.list_projects()
    finally:
        conn.close()

    if not projects:
        typer.echo("No projects found.")
        return

    typer.echo(f"{'ID':<38} {'Name':<30} Created")
    typer.echo("-" * 80)
    for p in projects:
        typer.echo(f"{p.id:<38} {p.name:<30} {p.created_at[:19]}")


@project_app.command("status")
def project_status_cmd(
    project_id: str = typer.Argument(..., help="Project UUID."),
    library: Optional[Path] = typer.Option(None, "--library", "-l", envvar="CITALIO_HOME"),
) -> None:
    """Show project details and decision statistics."""
    from citalio.db.project_repository import DocumentCitationRepository

    conn = open_and_migrate(library)
    try:
        repo = DocumentCitationRepository(conn)
        project = repo.get_project(project_id)
        if project is None:
            typer.echo(f"Project not found: {project_id}", err=True)
            raise typer.Exit(1)
        stats = repo.project_stats(project_id)
    finally:
        conn.close()

    typer.echo(f"ID:       {project.id}")
    typer.echo(f"Name:     {project.name}")
    typer.echo(f"Docx:     {project.docx_path or '—'}")
    typer.echo(f"Markdown: {project.markdown_path or '—'}")
    typer.echo(f"Sidecar:  {project.sidecar_path or '—'}")
    typer.echo(f"Style:    {project.citation_style_id or '—'}")
    typer.echo(f"Created:  {project.created_at[:19]}")
    typer.echo("")
    typer.echo("Decision counts:")
    anchors = stats.pop("anchors", {})
    for state, count in sorted(stats.items()):
        typer.echo(f"  {state:<20} {count}")
    if anchors:
        typer.echo("Anchor counts:")
        for status, count in sorted(anchors.items()):
            typer.echo(f"  {status:<20} {count}")


@project_app.command("sidecar-export")
def project_sidecar_export_cmd(
    project_id: str = typer.Argument(..., help="Project UUID."),
    out: Path = typer.Option(..., "--out", "-o", help="Output sidecar JSON file."),
    library: Optional[Path] = typer.Option(None, "--library", "-l", envvar="CITALIO_HOME"),
) -> None:
    """Export project anchors and decisions to a sidecar JSON file."""
    from citalio.core.sidecar import export_sidecar

    conn = open_and_migrate(library)
    try:
        export_sidecar(conn, project_id, out_path=out)
    finally:
        conn.close()

    typer.echo(f"Sidecar exported to {out}.")


@project_app.command("sidecar-import")
def project_sidecar_import_cmd(
    project_id: str = typer.Argument(..., help="Project UUID."),
    file: Path = typer.Option(..., "--file", "-f", help="Sidecar JSON file to import."),
    library: Optional[Path] = typer.Option(None, "--library", "-l", envvar="CITALIO_HOME"),
) -> None:
    """Import anchors and decisions from a sidecar JSON file into a project."""
    from citalio.core.sidecar import import_sidecar

    if not file.exists():
        typer.echo(f"File not found: {file}", err=True)
        raise typer.Exit(1)

    conn = open_and_migrate(library)
    try:
        anchors, decisions = import_sidecar(conn, project_id, file)
    finally:
        conn.close()

    typer.echo(f"Imported {anchors} anchor(s) and {decisions} decision(s) from {file}.")


# ---------------------------------------------------------------------------
# review sub-commands
# ---------------------------------------------------------------------------

@review_app.command("generate")
def review_generate_cmd(
    project_id: str = typer.Argument(..., help="Project UUID."),
    out: Path = typer.Option(..., "--out", "-o", help="Output .xlsx file."),
    states: Optional[str] = typer.Option(
        None, "--states", help="Comma-separated decision states to include (default: all)."
    ),
    library: Optional[Path] = typer.Option(None, "--library", "-l", envvar="CITALIO_HOME"),
) -> None:
    """Generate an Excel review sheet for citation candidates."""
    from citalio.review.excel_export import generate_review_excel

    state_list = [s.strip() for s in states.split(",")] if states else None
    conn = open_and_migrate(library)
    try:
        count = generate_review_excel(conn, project_id, out, states=state_list)
    finally:
        conn.close()

    typer.echo(f"Review sheet with {count} row(s) written to {out}.")


@review_app.command("apply")
def review_apply_cmd(
    project_id: str = typer.Argument(..., help="Project UUID."),
    file: Path = typer.Option(..., "--file", "-f", help="Completed review .xlsx file."),
    library: Optional[Path] = typer.Option(None, "--library", "-l", envvar="CITALIO_HOME"),
) -> None:
    """Apply an edited review sheet back to the database."""
    from citalio.review.excel_import import apply_review_excel

    if not file.exists():
        typer.echo(f"File not found: {file}", err=True)
        raise typer.Exit(1)

    conn = open_and_migrate(library)
    try:
        processed, updated = apply_review_excel(conn, project_id, file)
    finally:
        conn.close()

    typer.echo(f"Processed {processed} row(s), updated {updated} decision(s).")


# ---------------------------------------------------------------------------
# candidates sub-commands
# ---------------------------------------------------------------------------

@candidates_app.command("list")
def candidates_list_cmd(
    project_id: str = typer.Argument(..., help="Project UUID."),
    anchor: Optional[str] = typer.Option(None, "--anchor", "-a", help="Filter by anchor ID."),
    states: Optional[str] = typer.Option(
        None, "--states", help="Comma-separated states to include (default: all)."
    ),
    library: Optional[Path] = typer.Option(None, "--library", "-l", envvar="CITALIO_HOME"),
) -> None:
    """List citation candidates/decisions for a project."""
    from citalio.db.project_repository import DocumentCitationRepository

    state_list = [s.strip() for s in states.split(",")] if states else None
    conn = open_and_migrate(library)
    try:
        repo = DocumentCitationRepository(conn)
        decisions = repo.list_candidates(project_id, anchor_id=anchor, states=state_list)
    finally:
        conn.close()

    if not decisions:
        typer.echo("No decisions found.")
        return

    typer.echo(f"{'ID':<38} {'State':<16} {'Ref ID':<38} Cited for")
    typer.echo("-" * 110)
    for d in decisions:
        cited = (d.cited_for or "")[:40]
        typer.echo(f"{d.id:<38} {d.decision_state:<16} {d.reference_id or '':<38} {cited}")


@candidates_app.command("approve")
def candidates_approve_cmd(
    decision_id: str = typer.Argument(..., help="Decision UUID to approve."),
    library: Optional[Path] = typer.Option(None, "--library", "-l", envvar="CITALIO_HOME"),
) -> None:
    """Approve a citation candidate."""
    from citalio.db.project_repository import DocumentCitationRepository

    conn = open_and_migrate(library)
    try:
        repo = DocumentCitationRepository(conn)
        ok = repo.approve_decision(decision_id)
    finally:
        conn.close()

    if ok:
        typer.echo(f"Decision {decision_id} approved.")
    else:
        typer.echo(f"Decision not found: {decision_id}", err=True)
        raise typer.Exit(1)


@candidates_app.command("reject")
def candidates_reject_cmd(
    decision_id: str = typer.Argument(..., help="Decision UUID to reject."),
    reason: Optional[str] = typer.Option(None, "--reason", "-r", help="Rejection reason."),
    library: Optional[Path] = typer.Option(None, "--library", "-l", envvar="CITALIO_HOME"),
) -> None:
    """Reject a citation candidate."""
    from citalio.db.project_repository import DocumentCitationRepository

    conn = open_and_migrate(library)
    try:
        repo = DocumentCitationRepository(conn)
        ok = repo.reject_decision(decision_id, reason=reason)
    finally:
        conn.close()

    if ok:
        typer.echo(f"Decision {decision_id} rejected.")
    else:
        typer.echo(f"Decision not found: {decision_id}", err=True)
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# render sub-commands
# ---------------------------------------------------------------------------

@render_app.command("docx")
def render_docx_cmd(
    project_id: str = typer.Argument(..., help="Project UUID."),
    docx: Optional[Path] = typer.Option(
        None, "--docx", "-d",
        help="Word document with [@key] markers (default: project docx_path).",
    ),
    out: Optional[Path] = typer.Option(
        None, "--out", "-o",
        help="Output .docx file (default: <stem>_rendered.docx next to input).",
    ),
    no_bibliography: bool = typer.Option(
        False, "--no-bibliography", help="Skip appending a References section."
    ),
    library: Optional[Path] = typer.Option(None, "--library", "-l", envvar="CITALIO_HOME"),
) -> None:
    """[NOT YET AVAILABLE] Replace [@key] markers in a Word document (Step 9).

    Step 9 (Word document rendering) is currently parked as experimental.
    The paragraph-level replacement logic needs a safer implementation before
    production use.  This command will be re-enabled in a future release.

    For now, use 'citalio render markdown' (Step 8) to insert markers into
    a Markdown draft, which is fully supported.
    """
    # Step 9 / render_docx is experimental and its CLI entry point is
    # intentionally disabled.  The module is kept for future development.
    # See: citalio/rendering/word.py module docstring for details.
    typer.echo(
        "Error: 'render docx' (Step 9) is not yet available — "
        "the Word rendering module is experimental and not yet production-ready.\n"
        "Use 'citalio render markdown' (Step 8) instead.",
        err=True,
    )
    raise typer.Exit(1)


@render_app.command("markdown")
def render_markdown_cmd(
    project_id: str = typer.Argument(..., help="Project UUID."),
    out: Optional[Path] = typer.Option(
        None, "--out", "-o",
        help="Output markdown file (default: overwrites the project markdown_path).",
    ),
    library: Optional[Path] = typer.Option(None, "--library", "-l", envvar="CITALIO_HOME"),
) -> None:
    """[PROTOTYPE] Insert approved citation markers into the project markdown document (Step 8)."""
    from citalio.db.project_repository import DocumentCitationRepository
    from citalio.documents.markdown_insertion import insert_citations

    conn = open_and_migrate(library)
    try:
        repo = DocumentCitationRepository(conn)
        project = repo.get_project(project_id)
        if project is None:
            typer.echo(f"Project not found: {project_id}", err=True)
            raise typer.Exit(1)

        if not project.markdown_path:
            typer.echo("Project has no markdown_path configured.", err=True)
            raise typer.Exit(1)

        md_path = Path(project.markdown_path)
        if not md_path.exists():
            typer.echo(f"Markdown file not found: {md_path}", err=True)
            raise typer.Exit(1)

        output_path = out if out else md_path
        result = insert_citations(conn, project_id, md_path, output_path=output_path)
    finally:
        conn.close()

    typer.echo(
        f"Inserted: {result.inserted}  "
        f"Already present: {result.already_present}  "
        f"Anchor not found: {result.anchor_not_found}  "
        f"No marker: {result.no_marker}"
    )
    typer.echo(f"Output: {output_path}")


# ---------------------------------------------------------------------------
# validate sub-commands
# ---------------------------------------------------------------------------

@validate_app.command()
def validate_cmd(
    project_id: str = typer.Argument(..., help="Project UUID."),
    markdown: Optional[Path] = typer.Option(
        None, "--markdown", "-m",
        help="Markdown file to check for citation markers (defaults to project markdown_path).",
    ),
    report: Optional[Path] = typer.Option(
        None, "--report", "-r",
        help="Write validation report to this JSON file.",
    ),
    library: Optional[Path] = typer.Option(None, "--library", "-l", envvar="CITALIO_HOME"),
) -> None:
    """[PROTOTYPE] Validate citation decisions and document markers (Step 10)."""
    from citalio.db.project_repository import DocumentCitationRepository
    from citalio.validation.citation_validator import validate_project

    conn = open_and_migrate(library)
    try:
        repo = DocumentCitationRepository(conn)
        project = repo.get_project(project_id)
        if project is None:
            typer.echo(f"Project not found: {project_id}", err=True)
            raise typer.Exit(1)

        md_path = markdown
        if md_path is None and project.markdown_path:
            md_path = Path(project.markdown_path)

        result = validate_project(conn, project_id, markdown_path=md_path)
    finally:
        conn.close()

    typer.echo(result.summary())

    if result.issues:
        typer.echo("")
        for issue in result.issues:
            typer.echo(f"  [{issue.issue_type}] {issue.description}")

    if report:
        result.write_json(report)
        typer.echo(f"\nReport written to {report}.")

    if not result.is_valid:
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# gui sub-commands
# ---------------------------------------------------------------------------

gui_app = typer.Typer(help="[PROTOTYPE] Local web GUI commands (requires citalio[gui]).")
app.add_typer(gui_app, name="gui")


@gui_app.command("serve")
def gui_serve_cmd(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address."),
    port: int = typer.Option(8765, "--port", "-p", help="TCP port."),
    library: Optional[Path] = typer.Option(
        None,
        "--library",
        "-l",
        help="Path to the Citalio library directory.",
        envvar="CITALIO_HOME",
    ),
) -> None:
    """Start the Citalio local web GUI.

    Opens a browser-ready interface at http://HOST:PORT for managing
    references, reviewing citation decisions, and viewing validation reports.
    Requires: pip install 'citalio[gui]'
    """
    try:
        from citalio.gui.app import serve
    except ImportError:
        typer.echo(
            "citalio[gui] is required. Install with: pip install 'citalio[gui]'",
            err=True,
        )
        raise typer.Exit(1)

    serve(host=host, port=port, library=library)


# ---------------------------------------------------------------------------
# mcp sub-commands
# ---------------------------------------------------------------------------

mcp_app = typer.Typer(help="[PROTOTYPE] MCP server commands (requires citalio[mcp]).")
app.add_typer(mcp_app, name="mcp")


@mcp_app.command("serve")
def mcp_serve_cmd(
    library: Optional[Path] = typer.Option(
        None,
        "--library",
        "-l",
        help="Path to the Citalio library directory.",
        envvar="CITALIO_HOME",
    ),
    transport: str = typer.Option(
        "stdio",
        "--transport",
        help="MCP transport: 'stdio' (default) or 'sse'.",
    ),
) -> None:
    """Start the Citalio MCP server.

    By default runs over stdio, suitable for use as a Claude Code MCP server.
    Set --transport=sse for HTTP/SSE mode.
    """
    try:
        from citalio.mcp.server import create_server
    except ImportError:
        typer.echo(
            "citalio[mcp] is required. Install with: pip install 'citalio[mcp]'",
            err=True,
        )
        raise typer.Exit(1)

    server = create_server(library)
    server.run(transport=transport)


# ---------------------------------------------------------------------------
# embed sub-commands  (requires citalio[semantic])
# ---------------------------------------------------------------------------

embed_app = typer.Typer(help="[PROTOTYPE] Embedding and semantic indexing commands (requires citalio[semantic]).")
app.add_typer(embed_app, name="embed")


@embed_app.command("index")
def embed_index_cmd(
    reference_ids: Optional[list[str]] = typer.Argument(
        None, help="Reference UUIDs to index. Omit to index all references."
    ),
    connector: str = typer.Option(
        "bge-m3",
        "--connector",
        "-c",
        help="Embedding connector to use (bge-m3, openai, or a registered custom name).",
        envvar="CITALIO_EMBEDDING_MODEL",
    ),
    chunk_size: int = typer.Option(500, "--chunk-size", help="Tokens per chunk window."),
    overlap: int = typer.Option(50, "--overlap", help="Overlapping tokens between windows."),
    field: str = typer.Option(
        "abstract",
        "--field",
        "-f",
        help="Reference field to embed: 'abstract', 'title', or 'both'.",
    ),
    library: Optional[Path] = typer.Option(None, "--library", "-l", envvar="CITALIO_HOME"),
) -> None:
    """Embed reference text and store vectors in the chunks table.

    By default indexes the abstract of every reference in the library.
    Pass specific reference UUIDs to index only those records.

    Requires: pip install 'citalio[semantic]'

    Embedding model is configured via --connector / CITALIO_EMBEDDING_MODEL.
    See 'citalio embed info' for available connectors.
    """
    try:
        from citalio.connectors.llm import get_connector
        from citalio.search.semantic import SemanticIndex
    except ImportError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)

    from citalio.db.repository import CitationRepository

    conn = open_and_migrate(library)
    try:
        emb_connector = get_connector(connector)
        idx = SemanticIndex(conn, emb_connector)
        repo = CitationRepository(conn)

        all_refs = repo.list_references(limit=None)
        target_refs = (
            [r for r in all_refs if r.id in set(reference_ids)]
            if reference_ids
            else all_refs
        )

        if not target_refs:
            typer.echo("No matching references found.", err=True)
            raise typer.Exit(1)

        total_chunks = 0
        for ref in target_refs:
            parts: list[str] = []
            if field in ("title", "both") and ref.title:
                parts.append(ref.title)
            if field in ("abstract", "both") and ref.abstract:
                parts.append(ref.abstract)
            elif field == "abstract" and not ref.abstract and ref.title:
                parts.append(ref.title)  # fall back to title when abstract missing

            text = " ".join(parts)
            if not text.strip():
                continue

            chunk_ids = idx.index_reference(
                ref.id, text, chunk_size=chunk_size, overlap=overlap
            )
            total_chunks += len(chunk_ids)
            typer.echo(f"  Indexed {ref.id[:8]}… ({len(chunk_ids)} chunks)")

        typer.echo(f"\nDone. {len(target_refs)} references → {total_chunks} chunks [{connector}].")
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)
    finally:
        conn.close()


@embed_app.command("search")
def embed_search_cmd(
    query: str = typer.Argument(..., help="Natural-language search query."),
    limit: int = typer.Option(10, "--limit", "-n", help="Number of results to return."),
    connector: str = typer.Option(
        "bge-m3",
        "--connector",
        "-c",
        envvar="CITALIO_EMBEDDING_MODEL",
        help="Connector whose index to search.",
    ),
    library: Optional[Path] = typer.Option(None, "--library", "-l", envvar="CITALIO_HOME"),
) -> None:
    """Search indexed chunks by semantic similarity.

    Returns the top-N chunks closest to the query embedding, with their
    reference IDs and cosine similarity scores.

    Requires: pip install 'citalio[semantic]'
    """
    try:
        from citalio.connectors.llm import get_connector
        from citalio.search.semantic import SemanticIndex
    except ImportError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)

    conn = open_and_migrate(library)
    try:
        emb_connector = get_connector(connector)
        idx = SemanticIndex(conn, emb_connector)

        if idx.chunk_count() == 0:
            typer.echo(
                f"No chunks indexed for connector '{connector}'. "
                "Run 'citalio embed index' first.",
                err=True,
            )
            raise typer.Exit(1)

        results = idx.search(query, limit=limit)
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)
    finally:
        conn.close()

    if not results:
        typer.echo("No results.")
        return

    for i, r in enumerate(results, 1):
        typer.echo(
            f"{i:>2}. [{r.score:.3f}] ref={r.reference_id[:8]}…  "
            f"{r.text[:120].replace(chr(10), ' ')}"
        )


@embed_app.command("info")
def embed_info_cmd() -> None:
    """List available embedding connectors and their configuration."""
    try:
        from citalio.connectors.llm import list_connectors, get_connector
    except ImportError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)

    names = list_connectors()
    typer.echo("Available embedding connectors:\n")
    for name in names:
        c = get_connector(name)
        typer.echo(f"  {name:<16}  dimensions={c.dimensions}")
    typer.echo(
        "\nSet CITALIO_EMBEDDING_MODEL or use --connector to select one.\n"
        "Configure via connector.configure(**kwargs) in Python, or pass\n"
        "environment variables specific to each connector (e.g. OPENAI_API_KEY)."
    )


if __name__ == "__main__":
    app()

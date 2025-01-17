from flask import Blueprint, request

from sqlalchemy import text

from ..auth import auth
from ..db import db
from ..pagination import parse_pagination_params


leads_bp = Blueprint("leads", __name__)


@leads_bp.route("/leads", methods=["GET", "POST"])
@auth("user")
def leads_collection_view():
    if request.method == "GET":
        return _get_all_leads(request)
    elif request.method == "POST":
        # TODO: implement create method
        return _create_new_lead(request)
    return {
        "message": "Unknown http method",
    }, 404


# TODO: get these from a model
# TODO: allow filtering on fields
DEFAULT_LEAD_FIELDS = (
    "id",
    "company_name",
    "company_address",
    "formation_date",
    "contact_name",
    "website",
    "phone",
    "email",
    "twitter",
    "facebook",
    "linkedin",
    "last_email",
    "last_google_search",
    "last_twitter_search",
    "last_facebook_search",
    "last_linkedin_search",
    "instagram",
    "mission_statement",
    "programs",
    "populations_served",
    "county",
    "colorado_region",
    "data_source",
)


def _get_all_leads(request):
    # TODO: refactor by splitting into helper functions
    # parse query params
    # TODO: add search parameter
    # TODO: add filters
    try:
        page, perpage = parse_pagination_params(request)
        search = _parse_search_param(request)

        # removes fields with null values from the response
        drop_null = request.args.get("drop_null", "false").lower() == "true"
        include = request.args.get("include")
        if include is None:
            include = list(DEFAULT_LEAD_FIELDS)
        else:
            include = [field.lower().strip() for field in include.split(",") if field.lower() in DEFAULT_LEAD_FIELDS]

    except ValueError as e:
        # TODO: log error message
        return {
            "message": "invalid query parameters",
            "detail": {
                "error": str(e),
            },
        }, 400
    limit = perpage
    offset = (page - 1) * limit

    if search is None:
        query = text(
            """
            SELECT
                {columns}
            FROM LEADS
            ORDER BY id
            LIMIT :limit
            OFFSET :offset;
        """.format(
                columns=",".join(DEFAULT_LEAD_FIELDS)
            )
        )
        query_args = {
            "limit": limit,
            "offset": offset,
        }
    else:
        query = text(
            """
            SELECT
                {columns}
            FROM leads
            WHERE to_tsvector(company_name) @@ to_tsquery('{search}')
            ORDER BY ts_rank(to_tsvector(company_name), '{search}')
            LIMIT :limit
            OFFSET :offset
        """.format(
                columns=",".join(DEFAULT_LEAD_FIELDS),
                search=search,
            )
        )
        query_args = {
            "limit": limit,
            "offset": offset,
        }

    # TODO: handle database error
    # just grab all fields for now to avoid exposing query to sql injection
    with db.get_connection() as connection:
        res = connection.execute(query, **query_args)
        response_body = []
        count = 0
        for row in res:
            # TODO: handle potential errors if the user chooses a field not in the row
            lead = {field: getattr(row, field) for field in include}
            if drop_null:
                lead = {k: v for (k, v) in lead.items() if v is not None}
            response_body.append(lead)
            count += 1
        return {
            "count": count,
            "query": {
                "page": page,
                "perpage": perpage,
            },
            "leads": response_body,
        }, 200


def _parse_search_param(request):
    return request.args.get("search")


VALID_DATA_SOURCES = (
    "socrata",
    "colorado_nonprofit_association",
    "user_entry",
)


def _create_new_lead(request, valid_data_sources=VALID_DATA_SOURCES):
    # parse body params
    body = {
        field: value
        for (field, value) in request.get_json().items()
        if field != "id" and field in DEFAULT_LEAD_FIELDS and value is not None
    }

    # validate data source field
    data_source = body.get("data_source")
    if data_source:
        data_source = str(data_source).lower()
        if data_source not in valid_data_sources:
            return {"message": f'Invalid value for the "data_source" parameter: {data_source!r}'}, 422

    # insert into leads table
    # TODO: handle database error
    with db.get_engine().begin() as connection:
        row = connection.execute(
            text(
                """
                INSERT INTO leads ({columns})
                VALUES ({placeholders})
                RETURNING *;
                """.format(
                    columns=",".join(body.keys()),
                    placeholders=",".join(f":{column}" for column in body.keys()),
                )
            ),
            **body,
        ).first()
    return {field: getattr(row, field) for field in DEFAULT_LEAD_FIELDS}


@leads_bp.route("/leads/<int:id>", methods=["GET", "PUT", "DELETE"])
@auth("user")
def lead_view(id):
    if request.method == "GET":
        return _get_lead_by_id(id)
    elif request.method == "PUT":
        return _modify_lead_with_id(id, request)
    elif request.method == "DELETE":
        return _delete_lead_with_id(id)
    return {"message": "Unknown http method"}, 404


def _get_lead_by_id(id: int):
    # TODO: add include parameter for filtering on columns
    with db.get_connection() as connection:
        row = connection.execute(
            text(
                """
                SELECT {columns} FROM leads
                WHERE id = :id
            """.format(
                    columns=",".join(DEFAULT_LEAD_FIELDS)
                )
            ),
            id=id,
        ).first()
    if row is None:
        return {
            "params": {
                "id": id,
            },
            "message": "Could not find lead with given id.",
        }, 404
    return {field: getattr(row, field) for field in DEFAULT_LEAD_FIELDS}, 200


def _modify_lead_with_id(id: int, request):
    body = {
        field: value for (field, value) in request.get_json().items() if field != "id" and field in DEFAULT_LEAD_FIELDS
    }
    with db.get_engine().begin() as connection:
        row = connection.execute(
            text(
                """
                UPDATE leads
                SET {updates}
                WHERE id = :id
                RETURNING *;
            """.format(
                    updates=",".join(f"{field}=:{field}" for field in body.keys())
                )
            ),
            id=id,
            **body,
        ).first()

    if row is None:
        return {
            "params": {
                "id": id,
            },
            "body": request.get_json(),
            "message": "Could not find lead with given id.",
        }, 404

    return {field: getattr(row, field) for field in DEFAULT_LEAD_FIELDS}, 200


def _delete_lead_with_id(id: int):
    with db.get_engine().begin() as connection:
        row = connection.execute(
            text(
                """
                DELETE FROM leads
                WHERE id = :id
                RETURNING *;
            """
            ),
            id=id,
        ).first()

    if row is None:
        return {
            "params": {
                "id": id,
            },
            "message": "Could not find lead with given id.",
        }, 404

    return {field: getattr(row, field) for field in DEFAULT_LEAD_FIELDS}

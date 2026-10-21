"""
Connection to PostgreSQL/PostGIS.

- test(): checks that a connection can be established.
- list_schemas(): returns the list of schemas in the database.
- list_tables(schema): returns the tables/views of a schema.
- params()/from_params(): serialization hooks used by ConnectionStore.

Uses QGIS's own connection machinery (QgsProviderRegistry / the
'postgres' provider) instead of depending on psycopg2, which isn't
always installed in the QGIS Python environment.

Persistence (including encrypting the password via QgsAuthManager) is
handled by core.connection_store.ConnectionStore, so several named
Postgres connections can be saved side by side.
"""

from qgis.core import QgsDataSourceUri, QgsProviderRegistry

# QgsSettings group for the list of saved Postgres connections.
SETTINGS_GROUP = "SDIPublisher/connections/postgres"
AUTH_PREFIX = "SDIPublisher/postgres"


class PgConnection:
    def __init__(self, name="", host="localhost", port=5432, dbname="",
                 user="", password="", authcfg=None):
        self.name = name
        self.host = host
        self.port = int(port)
        self.dbname = dbname
        self.user = user
        self.password = password
        self.authcfg = authcfg   # QgsAuthManager reference, if any

    # --------------------------------------------------- store hooks
    def params(self):
        """Non-sensitive fields persisted by ConnectionStore."""
        return {"host": self.host, "port": self.port, "dbname": self.dbname}

    @classmethod
    def from_params(cls, name, params, user, password, authcfg):
        return cls(
            name=name,
            host=params.get("host", "localhost"),
            port=int(params.get("port", 5432)),
            dbname=params.get("dbname", ""),
            user=user,
            password=password,
            authcfg=authcfg,
        )

    def summary(self):
        """Short one-line label, e.g. 'user@host/db'."""
        return f"{self.user}@{self.host}/{self.dbname}"

    # --------------------------------------------------------------- URI
    def uri(self):
        uri = QgsDataSourceUri()
        uri.setConnection(self.host, str(self.port), self.dbname, self.user, self.password)
        return uri

    def _provider_connection(self):
        md = QgsProviderRegistry.instance().providerMetadata("postgres")
        if md is None:
            raise RuntimeError("The 'postgres' provider is not available in QGIS.")
        return md.createConnection(self.uri().uri(False), {})

    # --------------------------------------------------------------- test
    def test(self):
        """Return (True, "") if it can connect, or (False, error_message)."""
        try:
            conn = self._provider_connection()
            # A lightweight operation to force the actual connection.
            conn.schemas()
            return True, ""
        except Exception as e:
            return False, str(e)

    # ----------------------------------------------------------- schemas
    def list_schemas(self):
        """Return the list of schema names in the database."""
        conn = self._provider_connection()
        return sorted(conn.schemas())

    def list_tables(self, schema):
        """Return the table/view names of a schema."""
        conn = self._provider_connection()
        return sorted(t.tableName() for t in conn.tables(schema))

    # ----------------------------------------------------------- comments
    def get_table_comments(self, schema):
        """Return {table_name: comment_or_None} for every table in a schema, in one query."""
        conn = self._provider_connection()
        sql = (
            "SELECT c.relname, obj_description(c.oid, 'pg_class') "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            f"WHERE n.nspname = {_sql_literal(schema)} "
            "AND c.relkind IN ('r', 'v', 'm', 'f', 'p')"
        )
        rows = conn.executeSql(sql)
        return {row[0]: (row[1] or None) for row in rows} if rows else {}

    def set_table_comment(self, schema, table, comment):
        """Set (or clear, if comment is falsy) a table's COMMENT ON TABLE."""
        conn = self._provider_connection()
        value = _sql_literal(comment) if comment else "NULL"
        sql = f"COMMENT ON TABLE {_sql_ident(schema)}.{_sql_ident(table)} IS {value}"
        conn.executeSql(sql)

    # ----------------------------------------------------------- raw SQL
    def execute_sql(self, sql):
        """Run a read-only query and return its rows (list of lists)."""
        return self._provider_connection().executeSql(sql)


def _sql_ident(name):
    """Quote a SQL identifier (schema/table name)."""
    return '"' + str(name).replace('"', '""') + '"'


def _sql_literal(text):
    """Quote a SQL string literal."""
    return "'" + str(text).replace("'", "''") + "'"

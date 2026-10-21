# oci-cost-collector

oci-cost-collector loads the cost reports of an Oracle Cloud Infrastructure (OCI) tenancy into PostgreSQL. Each run loads the reports that are not in the database yet, and then exits. You can then query the cost and usage of each hour with SQL, for example from Grafana.

## How OCI cost reports work

OCI writes a cost report to Object Storage about every two to six hours. The report is a gzip CSV file. Oracle keeps the reports in the namespace `bling`, in a bucket that has the name of the tenancy OCID.

The usage of one hour arrives in pieces, over several reports. A report can contain usage up to about 24 hours before its creation time. To get the full usage of an hour, you add up the lines of all reports for that hour, resource, and product. The `hourly_usage` view does this.

The columns of a report are not fixed. OCI adds one `tags/...` column for each tag key in the tenancy. The order of these columns can change from one report to the next. OCI also adds new columns from time to time. The collector maps the columns by the header line, so it reads every report correctly.

## Why PostgreSQL and not Prometheus

A Prometheus exporter for the cost reports gives wrong numbers, because of four facts:

1. Prometheus stores each value at the time of the scrape. A cost report contains usage up to about 24 hours before its creation time. An exporter can only show that usage at the scrape time, so the chart shows the cost at the wrong hour.
2. The total of an hour changes after the fact. Each new report can add a piece to an hour, and a correction can reverse a line. Prometheus cannot change a value that it stored before.
3. Each resource and product is one series. With tags, the number of series grows fast.
4. Many Prometheus servers keep data for a few weeks. Oracle keeps cost reports for about one year.

PostgreSQL stores each report line with its usage hour. A query adds up all pieces of an hour at read time, so the result is correct also after a late piece or a correction.

You can still alert on the cost with Prometheus. Export a summary from SQL, for example the cost of the current month, and alert on that metric. With CloudNativePG, use a custom monitoring query, see [Read access](#read-access). Without CloudNativePG, you can use a SQL exporter, for example [sql_exporter](https://github.com/burningalchemist/sql_exporter).

## Requirements

- PostgreSQL 13 or later. The collector creates its tables and view at the start of each run.
- An OCI principal that can read the cost reports. If you use instance principal, put the instances in a dynamic group and add this policy in the root compartment of your tenancy:

  ```
  define tenancy usage-report as ocid1.tenancy.oc1..aaaaaaaaned4fkpkisbwjlr56u7cj63lf3wffbilvqknstgtvzub7vhqkggq
  endorse dynamic-group <your-dynamic-group> to read objects in tenancy usage-report
  ```

  If you use an OCI configuration file, the user of the file needs the same policy for its group: `endorse group <your-group> to read objects in tenancy usage-report`.

  The OCID in the `define` statement is the same for all customers. See [Accessing Cost and Usage Reports](https://docs.oracle.com/en-us/iaas/Content/Billing/Tasks/accessingusagereports.htm).

## Configuration

The collector reads its configuration from environment variables.

| Variable | Default | Description |
|---|---|---|
| `OCI_COST_TENANCY_ID` | none, required | The OCID of the tenancy. |
| `DATABASE_URL` | none, required | A libpq connection string or URI, for example `postgresql://user:password@host:5432/db`. |
| `OCI_COST_ACCOUNT` | the tenancy OCID | A short name for the tenancy. It goes in the `account` column, so that one database can hold several tenancies. |
| `OCI_COST_AUTH` | `instance_principal` | `instance_principal`, `resource_principal`, or `config_file`. |
| `OCI_COST_REGION` | the region of the principal | The region of the Object Storage endpoint. |
| `OCI_CONFIG_FILE` | `~/.oci/config` | The OCI configuration file, for `config_file`. |
| `OCI_CONFIG_PROFILE` | `DEFAULT` | The profile in the OCI configuration file. |
| `OCI_COST_READ_ROLES` | none | A comma-separated list of database roles. Each run grants them `SELECT` on the tables and the view. See [Read access](#read-access). |
| `OCI_COST_SINCE` | none | Load only the reports created at or after this time, for example `2026-01-01T00:00:00+00:00`. |
| `LOG_LEVEL` | `INFO` | `DEBUG` logs each report. |

The first run loads all reports in the bucket. Oracle keeps about one year of reports, so this run can take some time. The collector stores each report in its own transaction. If a run stops, the next run continues from the first report that is not stored.

## Run it

With Docker and an OCI configuration file:

1. Write a configuration file for the container, for example `./config`, whose `key_file` is `/oci/oci_api_key.pem`. See the example in [With an OCI configuration file](#with-an-oci-configuration-file).
2. Mount this file and your API key at `/oci` in the container:

   ```sh
   docker run --rm --read-only --user "$(id -u):$(id -g)" \
     -e OCI_COST_TENANCY_ID=ocid1.tenancy.oc1..example \
     -e OCI_COST_AUTH=config_file \
     -e OCI_CONFIG_FILE=/oci/config \
     -e DATABASE_URL=postgresql://user:password@db.example.com:5432/cost \
     -v "$PWD/config:/oci/config:ro" \
     -v "$HOME/.oci/oci_api_key.pem:/oci/oci_api_key.pem:ro" \
     ghcr.io/laobei2012/oci-cost-collector:0.2.0
   ```

The `--user` option runs the collector as your own user, so that it can read your key file. The key file must have the mode `0600` or less, and without this option, the user 10001 in the container cannot read it on Linux. Your user cannot open the home folder of the user 10001 in the container, so the files go to `/oci`, and `OCI_CONFIG_FILE` gives the path of the configuration file.

Do not mount your own `~/.oci` folder. `oci setup config` writes the absolute path of the key to `key_file`, for example `/Users/me/.oci/oci_api_key.pem`. That path does not exist in the container, so the collector cannot read the key.

## Run it on Kubernetes

Run the collector as a CronJob, for example once each hour. Set `concurrencyPolicy: Forbid`, so that a long first run does not overlap the next one. The first run loads about one year of reports, so give it an `activeDeadlineSeconds` of about one hour.

Both examples read `DATABASE_URL` from a Secret. With CloudNativePG, use the `uri` key of the Secret `<cluster>-app`.

### With instance principal

Use this method on OKE or on other OCI compute nodes. No Secret holds an OCI key. The pod uses the identity of its node, so it must run on nodes of the tenancy whose reports it reads. Put these nodes in the dynamic group of the policy in [Requirements](#requirements).

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: oci-cost-collector
spec:
  schedule: "17 * * * *"
  concurrencyPolicy: Forbid
  jobTemplate:
    spec:
      backoffLimit: 2
      activeDeadlineSeconds: 3600
      template:
        spec:
          restartPolicy: Never
          # Only the nodes of the tenancy. Use a label that your nodes have.
          nodeSelector:
            topology.kubernetes.io/region: phx
          containers:
            - name: collector
              image: ghcr.io/laobei2012/oci-cost-collector:0.2.0
              env:
                - name: OCI_COST_TENANCY_ID
                  value: ocid1.tenancy.oc1..example
                - name: DATABASE_URL
                  valueFrom:
                    secretKeyRef:
                      name: oci-cost-app
                      key: uri
              securityContext:
                allowPrivilegeEscalation: false
                readOnlyRootFilesystem: true
                runAsNonRoot: true
                capabilities:
                  drop: [ALL]
```

### With an OCI configuration file

Use this method on a cluster outside OCI. First, write a configuration file whose `key_file` is the path in the container. The same file works for the Docker example in [Run it](#run-it).

```ini
[DEFAULT]
user=ocid1.user.oc1..example
fingerprint=<fingerprint of the API key>
tenancy=ocid1.tenancy.oc1..example
region=us-phoenix-1
key_file=/oci/oci_api_key.pem
```

Then put the file and the private key in a Secret:

```sh
kubectl create secret generic oci-cost-oci-config \
  --from-file=config=./config \
  --from-file=oci_api_key.pem=./oci_api_key.pem
```

Mount the Secret at `/oci`, and set `OCI_COST_AUTH` and `OCI_CONFIG_FILE`. Use the CronJob above, without the `nodeSelector`, and change the pod part to this:

```yaml
          # The container runs as the user 10001. With fsGroup, Kubernetes
          # gives the files of the Secret to this group, so the user can read them.
          securityContext:
            fsGroup: 10001
          containers:
            - name: collector
              image: ghcr.io/laobei2012/oci-cost-collector:0.2.0
              env:
                - name: OCI_COST_AUTH
                  value: config_file
                - name: OCI_CONFIG_FILE
                  value: /oci/config
                - name: OCI_COST_TENANCY_ID
                  value: ocid1.tenancy.oc1..example
                - name: DATABASE_URL
                  valueFrom:
                    secretKeyRef:
                      name: oci-cost-app
                      key: uri
              volumeMounts:
                - name: oci-config
                  mountPath: /oci
                  readOnly: true
              securityContext:
                allowPrivilegeEscalation: false
                readOnlyRootFilesystem: true
                runAsNonRoot: true
                capabilities:
                  drop: [ALL]
          volumes:
            - name: oci-config
              secret:
                secretName: oci-cost-oci-config
                defaultMode: 0400
```

If you leave out `fsGroup`, the collector stops with `Permission denied` on the key file.

## Database

| Object | Content |
|---|---|
| `cost_report` | One row for each loaded report: `account`, `name`, `created_at`, `loaded_at`, `line_count`. |
| `cost_line` | One row for each report line, with all columns of the report. Tags are in the `tags` JSONB column, and unknown columns are in `extra`. |
| `hourly_usage` | A view that adds up the lines for each account, hour, resource, and product. |

Cost per day for each account:

```sql
SELECT account, date_trunc('day', hour) AS day, currency_code, sum(my_cost) AS cost
FROM hourly_usage
GROUP BY 1, 2, 3
ORDER BY 2;
```

Usage per hour of one product:

```sql
SELECT hour, account, sum(billed_quantity) AS quantity
FROM hourly_usage
WHERE product_description = 'Standard - A1'
GROUP BY 1, 2
ORDER BY 1;
```

The newest hours are not complete, because their remaining pieces are in reports that OCI did not write yet. Count an hour as complete about 30 hours after it ends.

## Read access

The collector owns its tables, so other roles cannot read them at first. Set `OCI_COST_READ_ROLES` to the roles that must read them, for example `OCI_COST_READ_ROLES=grafana,cnpg_metrics_exporter`. Each run grants these roles `SELECT` on `cost_report`, `cost_line`, and `hourly_usage`. So if you create the database again, the next run restores the grants.

If a role does not exist, the collector logs a warning and loads the reports.

With CloudNativePG, custom monitoring queries run as the role `cnpg_metrics_exporter`. Add this role to `OCI_COST_READ_ROLES` if such a query reads the cost tables.

## Limits

- The collector does not delete old data. One year of a small tenancy is about 190,000 lines and 160 MB.

## Corrections

When OCI changes a line that it already reported, it adds correction lines with `lineItem/isCorrection` set to `true`. A correction comes as a pair. The first line has the negative quantity and cost of the original line. The second line has the new values. `lineItem/backreferenceNo` of both lines points to the original line. The pair reverses the original line and then adds the new values. So the sum of all lines is correct, and `hourly_usage` needs no special rule for corrections.

## Development

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/ruff check . && .venv/bin/ruff format --check .
docker run -d --rm --name pg -e POSTGRES_PASSWORD=test -p 55432:5432 postgres:17-alpine
TEST_DATABASE_URL=postgresql://postgres:test@localhost:55432/postgres .venv/bin/pytest
```

Without `TEST_DATABASE_URL`, pytest skips the database tests.

## License

Apache License 2.0. See [LICENSE](LICENSE).

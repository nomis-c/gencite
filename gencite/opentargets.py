import requests

OPENTARGETS_URL = "https://api.platform.opentargets.org/api/v4/graphql"


def retrieve_open_targets_evidence(
    ensembl_id: str, max_diseases: int = 5
) -> list[dict]:

    query = """
    query TargetInfo($ensemblId: String!, $maxDiseases: Int!) {
      target(ensemblId: $ensemblId) {
        id
        approvedSymbol
        biotype
        associatedDiseases(page: {index: 0, size: $maxDiseases}) {
          rows {
            score
            disease {
              id
              name
            }
          }
        }
      }
    }
    """

    variables = {
        "ensemblId": ensembl_id,
        "maxDiseases": max_diseases,
    }

    response = requests.post(
        OPENTARGETS_URL,
        json={
            "query": query,
            "variables": variables,
        },
        timeout=15,
    )
    response.raise_for_status()

    payload = response.json()

    if "errors" in payload:
        raise RuntimeError(payload["errors"])

    target = payload.get("data", {}).get("target")

    if not target:
        return []

    evidence = []

    # Basic target information
    evidence.append(
        {
            "id": f"OT:target:{target['id']}",
            "source": "open_targets",
            "title": f"Target information for {target.get('approvedSymbol', ensembl_id)}",
            "text": (
                f"{target.get('approvedSymbol', ensembl_id)} "
                f"is annotated as gene biotype: "
                f"{target.get('biotype', 'unknown')}."
            ),
            "url": f"https://platform.opentargets.org/target/{target['id']}",
        }
    )

    # Disease associations
    rows = target.get("associatedDiseases", {}).get("rows", [])

    rows = sorted(
        rows,
        key=lambda row: row.get("score") or 0,
        reverse=True,
    )

    for row in rows:
        disease = row.get("disease", {})
        disease_id = disease.get("id")
        disease_name = disease.get("name")
        score = row.get("score")

        if not disease_id or not disease_name:
            continue

        evidence.append(
            {
                "id": f"OT:disease:{target['id']}:{disease_id}",
                "source": "open_targets",
                "title": f"Disease association: {disease_name}",
                "text": (
                    f"{target.get('approvedSymbol', ensembl_id)} is associated with "
                    f"{disease_name} in Open Targets "
                    f"(association score: {score:.3f})."
                    if score is not None
                    else f"{target.get('approvedSymbol', ensembl_id)} is associated with "
                    f"{disease_name} in Open Targets."
                ),
                "url": (
                    f"https://platform.opentargets.org/target/"
                    f"{target['id']}/associations"
                ),
            }
        )

    return evidence

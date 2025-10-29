import os
import httpx
import logging
from utils.date_utils import format_duration_clause
from oserver.connection import fetch_google_api_token_simple

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


async def fetch_keywords_service(
    client_code: str,
    customer_id: str,
    login_customer_id: str,
    campaign_id: str,
    duration: str,
) -> list:
    """
    Fetch active keywords and their metrics for a given campaign using a single keyword_view query.
    """
    try:
        # Step 1: Auth setup
        developer_token = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN")
        access_token = fetch_google_api_token_simple(client_code=client_code)


        if not developer_token or not access_token:
            raise ValueError("Missing Google Ads credentials or tokens.")

        endpoint = f"https://googleads.googleapis.com/v20/customers/{customer_id}/googleAds:search"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "developer-token": developer_token,
            "login-customer-id": login_customer_id,
            "Content-Type": "application/json",
        }

        duration_clause = format_duration_clause(duration)

        # Step 2: Single keyword_view query
        
        keyword_view_query = f"""
        SELECT
          campaign.id,
          campaign.name,
          ad_group.id,
          ad_group.name,
          ad_group_criterion.criterion_id,
          ad_group_criterion.status,
          ad_group_criterion.keyword.text,
          ad_group_criterion.keyword.match_type,
          ad_group_criterion.quality_info.quality_score,
          metrics.impressions,
          metrics.clicks,
          metrics.ctr,
          metrics.average_cpc,
          metrics.cost_micros,
          metrics.conversions
        FROM keyword_view
        WHERE
          campaign.id = {campaign_id}
          AND ad_group_criterion.negative = FALSE
          AND segments.date {duration_clause}
          AND ad_group_criterion.status = 'ENABLED'
          AND ad_group.status = 'ENABLED'
          AND campaign.status = 'ENABLED'
        ORDER BY ad_group.id, ad_group_criterion.criterion_id
        """

        # Step 3: Make API request
        async with httpx.AsyncClient() as client:
            response = await client.post(endpoint, headers=headers, json={"query": keyword_view_query})
            if not response.is_success:
                logger.error(f"Keyword fetch failed: {response.text}")
                response.raise_for_status()
            data = response.json().get("results", [])

        logger.info(f" Keyword View returned {len(data)} rows")

        # Step 4: Parse and normalize results
        def _safe_int(v):
            try:
                return int(float(v))
            except Exception:
                return 0

        def _safe_float(v):
            try:
                return float(v)
            except Exception:
                return 0.0

        def normalize(t: str) -> str:
            if not t:
                return ""
            t = t.lower().strip()
            for ch in ["-", "_", "+", ".", ","]:
                t = t.replace(ch, " ")
            return " ".join(t.split())

        # Step 5: Build structured result list
        keywords = []
        for row in data:
            ad_group = row.get("adGroup", {})
            ad_group_criterion = row.get("adGroupCriterion", {})
            keyword_info = ad_group_criterion.get("keyword", {})
            metrics = row.get("metrics", {})

            keyword_text = normalize(keyword_info.get("text"))
            match_type = keyword_info.get("matchType")

            if not keyword_text or not match_type:
                continue

            imp = _safe_int(metrics.get("impressions"))
            clk = _safe_int(metrics.get("clicks"))
            cost = _safe_int(metrics.get("costMicros"))
            conv = _safe_float(metrics.get("conversions"))
            ctr = round((clk / imp) * 100, 2) if imp > 0 else 0.0
            avg_cpc = round((cost / clk / 1_000_000), 2) if clk > 0 else 0.0

            keywords.append({
                "campaign_id": row.get("campaign", {}).get("id"),
                "campaign_name": row.get("campaign", {}).get("name"),
                "ad_group_id": ad_group.get("id"),
                "ad_group_name": ad_group.get("name"),
                "criterion_id": ad_group_criterion.get("criterionId"),
                "status": ad_group_criterion.get("status"),
                "keyword": keyword_text,
                "match_type": match_type,
                "quality_score": ad_group_criterion.get("qualityInfo", {}).get("qualityScore"),
                "impressions": imp,
                "clicks": clk,
                "ctr": ctr,
                "average_cpc": avg_cpc,
                "cost_micros": cost,
                "conversions": conv,
            })

        logger.info(f"Final keyword count: {len(keywords)}")
        return keywords

    except httpx.RequestError as e:
        logger.error(f"Request failed: {e}")
        return []
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        return []

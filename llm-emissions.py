#!/usr/bin/env python3

import sys

import click

# Sources:
# [S1] Anthropic SEC S-1 Filing
# https://www.sec.gov/Archives/edgar/data/2130357/000162828026072484/anthropicpbc-sx1ax2.htm
#
# [S2] Schneider, Xu, Benecke, et al.: Life-Cycle Emissions of AI Hardware: A Cradle-To-Grave Approach and Generational
# Trends
# https://arxiv.org/abs/2502.01671
#
# [S3] US DoE NREL: Life Cycle Greenhouse Gas Emissions from Electricity Generation: Update
# https://docs.nlr.gov/docs/fy21osti/80580.pdf
#
# [S4] Anthropic press release on SpaceX deal
# https://www.anthropic.com/news/higher-limits-spacex
#
# [S5] SpaceX SEC S-1 Filing
# https://www.sec.gov/Archives/edgar/data/1181412/000162828026040364/spaceexplorationtechnologib.htm
#
# [S6] Shehabi, Smith, Hubbard et. al.: 2024 United States Data Center Energy Usage Report
# https://eta-publications.lbl.gov/sites/default/files/2024-12/us_data_center_energy_usage_report_lbnl-2001637.pdf
#

# === How much expenses did Anthropic have for 1$ of revenue? ===
# [S1] 2026 numbers
revenue = 33242e6
cost_of_revenue = 4812e6

infrastructure_cost_per_revenue_usd = cost_of_revenue / revenue # ~= 0.14 USD

# === How much revenue does Anthropic book for 1$ of API expenses? ===

# [S1] 2026 numbers
api_revenue_share = 0.79 # pg. 144, keyword: consumption-based revenue
subscription_revenue_share = 1 - api_revenue_share # subscriptions make up the remainder

# How much does the average API customer pay for 1$ of billed usage?
api_realised_per_list_usd = 0.85 # Pure assumption, we don't have hard numbers.

# How much usage in equivalent API billing does the average 1$ of subscription revenue cause?
subscription_list_usd_per_revenue_usd = 2.0 # Pure assummption as well. 

list_usage_per_revenue_usd = (api_revenue_share / api_realised_per_list_usd
                              + subscription_revenue_share * subscription_list_usd_per_revenue_usd)

booked_revenue_usd_per_api_usd = 1 / list_usage_per_revenue_usd # ~= 0.74 USD

hours_per_month = 365.25 * 24 / 12
spacex_kw = 300e3 # from [S4]
spacex_cost_usd_per_month = 1.25e9 # from [S5]

# S5 describes later figures that include additional GPUs, but has no power figures.
# S4 has power figures, but only describes a fraction of the GPUs in S5 and has not cost information.
# We correct for that by scaling the power from S4 by the GPU count from S5.
s4_gpus = 220e3 # [S4]
s5_gpus = 325e3 # [S5]
correction = s5_gpus / s4_gpus

datacenter_kwh_per_cost_usd = spacex_kw * correction * hours_per_month / spacex_cost_usd_per_month # ~ 0.26 kWh / USD

power_usage_efficiency = 1.3 # Pessimistic value taken from projection reported in [S6]

# [S3]
electricity_generation_gas_co2_per_kwh = 0.486

# S2, Table 1
# 1 kg of CO2 emitted for operation (power) corresponds to roughly 0.1 kg extra CO2 from embodied emissions, i.e. from
# device manufacturing.
embodied_co2_emission_factor = 1.1

@click.command()
@click.argument('session_equivalent_api_price_usd', type=float)
def cli(session_equivalent_api_price_usd):
    booked_revenue = session_equivalent_api_price_usd * booked_revenue_usd_per_api_usd

    # pessimal assumption: infrastructure_cost is all datacenter computing and infrastructure cost, none of it is other
    # overhead such as personnel cost
    infrastructure_cost = booked_revenue * infrastructure_cost_per_revenue_usd

    datacenter_kwh = infrastructure_cost * datacenter_kwh_per_cost_usd * power_usage_efficiency
    # pessimal assumption: datacenter_kwh comes entirely from carbon-intensive gas power plants
    datacenter_co2 = datacenter_kwh * electricity_generation_gas_co2_per_kwh * embodied_co2_emission_factor
    print(f'Corresponding CO2 emissions: {datacenter_co2:.2f} kg CO2')

if __name__ == '__main__':
    cli()

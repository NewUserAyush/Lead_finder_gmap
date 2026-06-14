# Lead_finder_gmap


# A. You have GSC + GA4 API access — full auto-pull
python3 generate.py results --auto --template > acme.json   # then edit acme.json
python3 generate.py results --auto acme.json

# B. Client holds GSC, you have GA4 — client gives you their GSC numbers
#    (use client_no_gsc.json: it has a "gsc" block with their figures)
python3 generate.py results --auto client_no_gsc.json

# C. No GSC at all — DataForSEO estimated traffic
#    (use client_dataforseo_traffic.json: it has "traffic_source": "dataforseo")
python3 generate.py results --auto client_dataforseo_traffic.json

# Manual — paste every number, no pulls (uses the plain client.json shape)
python3 generate.py results client.json


python3 generate.py prospect pawspace.in --currency inr --aov 1500 --location 2356
# or skip the DataForSEO pull and pass traffic yourself:
python3 generate.py prospect acme.com --currency usd --aov 240 --visitors 12000
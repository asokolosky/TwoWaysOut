"""Tiny SAM and assessment CSVs that mirror the real column layout. Names are fictional."""

SAM_CSV = """\
SAM_ADDRESS_ID,BUILDING_ID,RELATIONSHIP_TYPE,FULL_ADDRESS,STREET_NUMBER,IS_RANGE,RANGE_FROM,RANGE_TO,UNIT,FULL_STREET_NAME,STREET_ID,STREET_PREFIX,STREET_BODY,STREET_SUFFIX_ABBR,STREET_FULL_SUFFIX,STREET_SUFFIX_DIR,STREET_NUMBER_SORT,MAILING_NEIGHBORHOOD,ZIP_CODE,X_COORD,Y_COORD,SAM_STREET_ID,WARD,MAP_PAR_ID,PARCEL_ID,SEGMENT_ID,trash_day,created_date,last_edited_date,shape_wkt,POINT_X,POINT_Y
1,10,1,182 London St,182,0,,,,London St,1,,London,St,Street,,182,East Boston,02128,0,0,1,01,0106069000,0106069000,1,T,,,,-71.037,42.375
2,10,2,182 London St #2,182,0,,,2,London St,1,,London,St,Street,,182,East Boston,02128,0,0,1,01,0106069000,0106069000,1,T,,,,-71.037,42.375
3,11,1,181-183 State St,181-183,1,181,183,,State St,2,,State,St,Street,,181,Boston,02109,0,0,2,03,0303807000,0303807000,1,T,,,,-71.052,42.359
4,12,1,10 Oak Ave,10,0,,,,Oak Ave,3,,Oak,Ave,Avenue,,10,Dorchester,02122,0,0,3,15,1500001000,1500001000,1,T,,,,-71.05,42.30
5,13,1,10 Oak Ave,10,0,,,,Oak Ave,4,,Oak,Ave,Avenue,,10,Roslindale,02131,0,0,4,19,1900001000,1900001000,1,T,,,,-71.12,42.28
6,14,1,217 Lexington St,217,0,,,,Lexington St,5,,Lexington,St,Street,,217,East Boston,02128,0,0,5,01,0100010000,0100010000,1,T,,,,-71.03,42.37
7,15,1,5 Elm St,5,0,,,,Elm St,6,,Elm,St,Street,,5,Allston,02134,0,0,6,22,2200001000,2200001000,1,T,,,,-71.13,42.36
8,16,1,9 Mount Vernon St,9,0,,,,Mount Vernon St,7,,Mount Vernon,St,Street,,9,Boston,02108,0,0,7,05,0500001000,0500001000,1,T,,,,-71.06,42.35
"""

# OWNER and MAIL_* columns are present here on purpose: preprocessing must drop them.
ASSESSMENT_CSV = """\
PID,CM_ID,GIS_ID,ST_NUM,ST_NAME,UNIT_NUM,CITY,ZIP_CODE,LU,LU_DESC,BLDG_TYPE,OWN_OCC,OWNER,MAIL_ADDRESSEE,MAIL_STREET_ADDRESS,MAIL_CITY,MAIL_STATE,MAIL_ZIP_CODE,RES_UNITS,YR_BUILT,YR_REMODEL,HEAT_TYPE
0106069000,,0106069000,182,London ST,,EAST BOSTON,02128,R3,THREE-FAM DWELLING,,Y,TEST OWNER ONE,,1 SECRET RD,NOWHERE,MA,00000,,1910,,W - Ht Water/Steam
0303807000,,0303807000,181,State ST,,BOSTON,02109,C,COMMERCIAL,,N,TEST OWNER TWO,,2 SECRET RD,NOWHERE,MA,00000,,1999,,
1500001000,,1500001000,10,Oak AV,,DORCHESTER,02122,R1,SINGLE FAM DWELLING,,Y,TEST OWNER THREE,,3 SECRET RD,NOWHERE,MA,00000,,1925,,F - Forced Hot Air
1900001000,,1900001000,10,Oak AV,,ROSLINDALE,02131,R1,SINGLE FAM DWELLING,,N,TEST OWNER FOUR,,4 SECRET RD,NOWHERE,MA,00000,,1930,,
0100010000,0100010000,0100010000,217,Lexington ST,,EAST BOSTON,02128,CM,CONDO MAIN,,N,TEST OWNER FIVE,,,,,,,1900,,
0100010002,0100010000,0100010000,217,Lexington ST,1,EAST BOSTON,02128,CD,RESIDENTIAL CONDO,,Y,TEST OWNER SIX,,,,,,,1900,2020,F - Forced Hot Air
0100010004,0100010000,0100010000,217,Lexington ST,2,EAST BOSTON,02128,CD,RESIDENTIAL CONDO,,N,TEST OWNER SEVEN,,,,,,,1900,,F - Forced Hot Air
2200001000,2200001000,2200001000,5,Elm ST,,ALLSTON,02134,CM,CONDO MAIN,,N,TEST OWNER EIGHT,,,,,,,1950,,
2200001002,2200001000,2200001000,5,Elm ST,1,ALLSTON,02134,CD,RESIDENTIAL CONDO,,Y,TEST OWNER NINE,,,,,,,1950,,
0500001000,,0500001000,9,Mount Vernon ST,,BOSTON,02108,CD,RESIDENTIAL CONDO,,N,TEST OWNER TEN,,,,,,,1840,,
"""

# Real description strings from RentSmart. The owner column is present on purpose.
RENTSMART_CSV = """\
date,violation_type,description,address,neighborhood,zip_code,parcel,owner,year_built,year_remodeled,property_type,latitude,longitude
2026-09-01 10:00:00+00,Housing Violations,"The owner shall provide, install, and maintain in operable condition smoke detectors and carbon monoxide alarms in every residence is required","182 London St, 02128",East Boston,02128,0106069000,TEST OWNER ONE,1910,,Residential 3-family,42.37,-71.03
2026-01-15 10:00:00+00,Housing Complaints,"Heat - Excessive, Insufficient","182 London St 2, 02128",East Boston,02128,0106069000,TEST OWNER ONE,1910,,Residential 3-family,42.37,-71.03
2024-03-02 10:00:00+00,Housing Complaints,Egress,"182 London St, 02128",East Boston,02128,0106069000,TEST OWNER ONE,1910,,Residential 3-family,42.37,-71.03
2026-08-01 10:00:00+00,Enforcement Violations,Improper storage trash: res,"182 London St, 02128",East Boston,02128,0106069000,TEST OWNER ONE,1910,,Residential 3-family,42.37,-71.03
2026-07-01 10:00:00+00,Housing Violations,"The owner shall provide the electricity or gas used in each dwelling unit unless: the utility is seperated and there is a written rental agreement","182 London St, 02128",East Boston,02128,0106069000,TEST OWNER ONE,1910,,Residential 3-family,42.37,-71.03
2026-06-01 10:00:00+00,Housing Complaints,Electrical,"10 Oak Ave, 02122",Dorchester,02122,1500001000,TEST OWNER THREE,1925,,Residential 1-family,42.30,-71.05
2026-05-01 10:00:00+00,Housing Violations,Failure to provide a smoke detector or carbon monoxide alarm required by 105 CMR 410.330.,"217 Lexington St 2, 02128",East Boston,02128,0100010004,TEST OWNER SEVEN,1900,,Residential Condo,42.37,-71.03
"""

# The contact_* columns are present on purpose.
VIOLATIONS_CSV = """\
case_no,ap_case_defn_key,status_dttm,status,code,value,description,violation_stno,violation_sthigh,violation_street,violation_suffix,violation_city,violation_state,violation_zip,ward,contact_addr1,contact_addr2,contact_city,contact_state,contact_zip,sam_id,latitude,longitude,location
V1,1013,2026-02-01 09:00:00,Open,1031.3,N/A,Means of Egress,182,,London,ST,East Boston,MA,02128,01,1 SECRET RD,,NOWHERE,MA,00000,2,42.37,-71.03,
V2,1013,2025-05-01 09:00:00,Closed,903,N/A,Fire Protection Systems,182,,London,ST,East Boston,MA,02128,01,1 SECRET RD,,NOWHERE,MA,00000,1,42.37,-71.03,
V3,1013,2026-03-01 09:00:00,Open,121.2,N/A,Unsafe and Dangerous,182,,London,ST,East Boston,MA,02128,01,1 SECRET RD,,NOWHERE,MA,00000,1,42.37,-71.03,
"""

# applicant and comments are present on purpose.
PERMITS_CSV = """\
permitnumber,worktype,permittypedescr,description,comments,applicant,declared_valuation,total_fees,issued_date,expiration_date,status,occupancytype,sq_feet,address,city,state,zip,ward,property_id,parcel_id,gpsy,gpsx,y_latitude,x_longitude
P1,FA,Electrical Fire Alarms,Fire Alarm,Call TEST APPLICANT at home,TEST APPLICANT,$1,$1,2019-04-01T10:00:00,2019-10-01T04:00:00,Closed,1-3FAM,0,182 London ST,East Boston,MA,02128,1,1,106069000,0,0,0,0
P2,ELECTRICAL,Electrical Permit,Electrical,,TEST APPLICANT,$1,$1,1999-01-01T10:00:00,1999-06-01T04:00:00,Closed,1-3FAM,0,182 London ST,East Boston,MA,02128,1,1,106069000,0,0,0,0
P3,PLUMBING,Plumbing Permit,Plumbing,,TEST APPLICANT,$1,$1,2022-01-01T10:00:00,2022-06-01T04:00:00,Closed,1-3FAM,0,182 London ST,East Boston,MA,02128,1,1,106069000,0,0,0,0
P4,ELECTRICAL,Electrical Permit,Electrical,,TEST APPLICANT,$1,$1,2023-01-01T10:00:00,2023-06-01T04:00:00,Open,1FAM,0,10 Oak AV,Dorchester,MA,02122,15,4,1500001000,0,0,0,0
C1,ERECT,Erect/New Construction,SECRET new 5 story building,SECRET call the GC,TEST APPLICANT,"$2,345,678.00",$1,2026-03-10T10:00:00,2027-03-10T04:00:00,Open,Multi,0,184 London ST,East Boston,MA,02128,1,9,106070000,0,0,42.3752,-71.037
C2,OTHER,Foundation Permit,SECRET foundation,,TEST APPLICANT,"$400,000.00",$1,2026-01-05T10:00:00,2027-01-05T04:00:00,Open,Multi,0,186 London ST,East Boston,MA,02128,1,9,106070000,0,0,42.37522,-71.037
C3,INTREN,Long Form/Alteration Permit,SECRET gut renovation,,TEST APPLICANT,"$500,000.00",$1,2025-06-15T10:00:00,2026-06-15T04:00:00,Closed,3FAM,0,230 London ST,East Boston,MA,02128,1,10,106080000,0,0,42.3765,-71.037
C4,INTREN,Long Form/Alteration Permit,SECRET new kitchen,,TEST APPLICANT,"$20,000.00",$1,2026-02-01T10:00:00,2027-02-01T04:00:00,Open,3FAM,0,190 London ST,East Boston,MA,02128,1,11,106090000,0,0,42.3753,-71.0372
C5,ADDITION,Long Form/Alteration Permit,SECRET rear addition,,TEST APPLICANT,"$300,000.00",$1,2026-04-01T10:00:00,2027-04-01T04:00:00,Open,3FAM,0,182 London ST,East Boston,MA,02128,1,1,106069000,0,0,42.375,-71.037
C6,ERECT,Erect/New Construction,SECRET old project,,TEST APPLICANT,"$900,000.00",$1,2022-01-01T10:00:00,2023-01-01T04:00:00,Closed,Multi,0,200 London ST,East Boston,MA,02128,1,12,106100000,0,0,42.3758,-71.037
C7,RAZE,Short Form Bldg Permit,SECRET raze garage,,TEST APPLICANT,"$30,000.00",$1,2026-05-01T10:00:00,2027-05-01T04:00:00,Open,Garage,0,300 London ST,East Boston,MA,02128,1,13,106110000,0,0,42.38,-71.037
C8,INTDEM,Short Form Bldg Permit,SECRET interior demo,,TEST APPLICANT,"$900,000.00",$1,2026-05-01T10:00:00,2027-05-01T04:00:00,Open,3FAM,0,188 London ST,East Boston,MA,02128,1,14,106120000,0,0,42.3751,-71.0371
"""

# Data Commons /v2/observation response shape (values are made up for the fixture).
DATACOMMONS_JSON = {
    "source": "Data Commons (datacommons.org), U.S. Census American Community Survey",
    "fetched": "2026-10-20",
    "places": [
        {
            "zip": "02128",
            "housing_units": 20000,
            "built_before_1940": 9000,
            "renter_occupied": 12000,
            "owner_occupied": 6000,
            "dates": {"housing_units": "2024", "built_before_1940": "2024", "renter_occupied": "2024", "owner_occupied": "2024"},
        },
        {
            "zip": "01002",
            "housing_units": 11568,
            "built_before_1940": 2706,
            "renter_occupied": 5475,
            "owner_occupied": 4845,
            "dates": {"housing_units": "2024", "built_before_1940": "2024", "renter_occupied": "2024", "owner_occupied": "2024"},
        },
    ],
}

import datetime as dt
import json
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('collect',Path(__file__).parents[1]/'scripts/collect.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class CollectorTests(unittest.TestCase):
    def test_missing_is_not_zero(self):
        self.assertIsNone(m.number('-'))
        self.assertIsNone(m.number(''))
        self.assertEqual(m.number('0,0'),0)

    def test_snow_requires_cm_and_context(self):
        self.assertEqual(m.snow_range('Neige. Accumulation de 5 à 10 cm.'),[5,10])
        self.assertIsNone(m.snow_range('Pluie de 10 mm.'))
        self.assertIsNone(m.snow_range('Vent de 50 km/h.'))

    def test_consensus_aligns_periods_and_excludes_stale(self):
        day=str(m.TODAY)
        def s(key,amount,status='ok',period='00-24-local'):
            return {'id':key,'status':status,'days':[{'date':day,'snow_cm':amount,'snow_period':period,'risk':'Neige','high':0,'low':-2}]}
        rows=[s('a',[3,7]),s('b',[8,12]),s('c',None),s('d',[100,100],'stale'),s('e',[50,50],period='jour-nuit')]
        q=m.consensus(rows)[0]['snow']
        self.assertEqual(q['count'],2)
        self.assertEqual(q['mean_cm'],7.5)
        self.assertEqual(q['median_cm'],7.5)
        self.assertEqual(q['min_cm'],3)
        self.assertEqual(q['max_cm'],12)
        self.assertIsNone(m.consensus([s('a',[5,5])])[0]['snow']['mean_cm'])

    def test_climate_columns_and_incomplete(self):
        def row(day,snow,flag=''):
            cells=[day,'1','','0','','-1','','','2','',snow,flag,'4','','8','','-']
            return '<tr>'+''.join('<td>'+x+'</td>' for x in cells)+'</tr>'
        html='Saint-Prosper 7027660<table>'+row('01','5,5')+row('02','9,0','I')+row('03','-')+'</table>'
        with patch.object(m,'fetch',return_value=html):
            rows=m.climat_month(2025,11)
        self.assertEqual(rows[0]['snow_cm'],5.5)
        self.assertEqual(rows[0]['depth_cm'],8)
        self.assertIsNone(rows[1]['snow_cm'])
        self.assertIsNone(rows[2]['snow_cm'])

    def test_crossing_threshold_is_a_change(self):
        before={'sources':[{'id':'a','status':'ok','days':[{'date':'2026-11-10','risk':'Neige','snow_cm':[2,4]}]}]}
        after={'sources':[{'id':'a','name':'Source A','status':'ok','days':[{'date':'2026-11-10','risk':'Neige','snow_cm':[4,6]}]}]}
        self.assertTrue(m.changes(before,after)[0]['important'])

    def test_risk(self):
        self.assertEqual(m.risk('Neige mêlée de pluie'),'Pluie / neige')
        self.assertEqual(m.risk('Pluie verglaçante'),'Verglas / grésil')
        self.assertEqual(m.risk('AM Rain/Snow Showers'),'Pluie / neige')
        self.assertEqual(m.risk('Précipitations mixtes'),'Pluie / neige')
        self.assertEqual(m.risk('Quelques flocons'),'Neige')

    def test_meteomedia_structured_table(self):
        def col(name,vals):
            return {'csvw:name':name,'csvw:cells':[{'csvw:value':v} for v in vals]}
        parts=['Nuit','Matin','Après-midi','Soir']
        data={'@type':'Dataset','name':'Prévisions météorologiques à court terme - Saint-Prosper, Québec','mainEntity':{'csvw:tableSchema':{'csvw:columns':[
            col('date',['2026-11-12']*4+['2026-11-13']*4),col('timeOfDay',parts*2),
            col('condition',['Faible neige','Neige','Quelques flocons','Ciel variable']*2),
            col('temperature',['-2°C','-1°C','0°C','-3°C']*2),col('snow',['2-4 cm','1-3 cm','<1 cm','0 cm']*2),col('rain',['0 mm']*8)]}}}
        html='<script type="application/ld+json">'+json.dumps(data)+'</script>'
        with patch.object(m,'fetch',return_value=html):
            with self.assertRaises(ValueError):  # 2 jours seulement : trop court
                m.mm()
        rows=m.mm_table(html)
        self.assertEqual(rows[0]['snow'],'2-4 cm')
        self.assertEqual(m.amount('2-4 cm'),[2,4])
        self.assertEqual(m.amount('<1 cm'),[0,1])
        self.assertIsNone(m.amount('—'))

    def test_winter_rollover(self):
        self.assertEqual(m.season_year(dt.date(2027,2,1)),2026)
        self.assertEqual(m.season_year(dt.date(2027,11,1)),2027)

if __name__=='__main__':unittest.main()

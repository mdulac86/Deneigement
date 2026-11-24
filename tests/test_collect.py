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
        q=m.consensus([s('a',[5,8]),s('b',[6,10]),s('c',[5,9]),s('z',[28,32])])[0]['snow']  # une source à 30 cm
        self.assertEqual((q['max_cm'],q['count'],q['ecartes']),(10,3,{'z':30.0}))

    def test_risk_alerts_need_official_two_sources_or_trusted(self):
        day=str(m.TODAY)
        def s(key,risk):
            return {'id':key,'status':'ok','days':[{'date':day,'risk':risk,'high':0,'low':-2}]}
        def confirmed(rows,table=None,extra=()):
            r={'consensus':m.consensus(rows),'confiance':table or {}}
            r['consensus'][0]['risks']+=list(extra)
            m.confirm_risks(r)
            return r['consensus'][0]
        d=confirmed([s('mb','Verglas / grésil'),s('met','Neige')])
        self.assertEqual(d['risques_confirmes'],[])  # une seule source non mesurée par risque
        self.assertEqual({x['source'] for x in d['risques_a_confirmer']},{'mb','met'})
        self.assertIn('Verglas / grésil',d['risks'])  # toujours affiché
        self.assertEqual(confirmed([s('eccc','Verglas / grésil')])['risques_confirmes'],['Verglas / grésil'])
        self.assertEqual(confirmed([s('mb','Neige'),s('mm','Neige')])['risques_confirmes'],['Neige'])
        sure={'mm':{'poids':0.9,'statut':'mesurée'}}
        self.assertEqual(confirmed([s('mm','Neige')],sure)['risques_confirmes'],['Neige'])
        self.assertEqual(confirmed([s('mb','Neige')],extra=['Poudrerie'])['risques_confirmes'],['Poudrerie'])  # issu des modèles

    def test_storm_flag_switches_to_hourly(self):
        now=dt.datetime(2026,12,9,17,tzinfo=dt.timezone.utc)
        p=lambda statut,debut,fin:{'statut':statut,'debut':debut,'fin':fin,'depart':debut}
        self.assertTrue(m.tempete({'plan':[p('sortie','2026-12-10T22:00:00-05:00','2026-12-11T06:00:00-05:00')]},now)['active'])  # dans 34 h
        self.assertFalse(m.tempete({'plan':[p('sortie','2026-12-11T08:00:00-05:00','2026-12-11T12:00:00-05:00')]},now)['active'])  # dans 44 h
        self.assertFalse(m.tempete({'plan':[p('sous_seuil','2026-12-09T22:00:00-05:00','2026-12-10T02:00:00-05:00')]},now)['active'])
        self.assertTrue(m.tempete({'plan':[p('possible','2026-12-09T08:00:00-05:00','2026-12-09T11:00:00-05:00')]},now)['active'])  # en cours (+2 h)
        self.assertTrue(m.tempete({'plan':[],'official_alerts':{'items':[{'id':'x'}]}},now)['active'])
        self.assertFalse(m.tempete({'plan':[]},now)['active'])

    def test_quick_hrrr_keeps_the_48h_tail(self):
        new={'hours':[{'time':'2026-12-09T%02d:00:00Z'%h,'snow_cm':1} for h in range(12,18)],'note':'HRRR.'}
        old={'status':'ok','hours':[{'time':'2026-12-09T%02d:00:00Z'%h,'snow_cm':0} for h in range(6,24)]}
        out=m.merge_tail(new,old)
        self.assertEqual([h['snow_cm'] for h in out['hours']],[1]*6+[0]*6)
        self.assertEqual(out['hours'][-1]['time'],'2026-12-09T23:00:00Z')

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

    def test_relay_is_used_only_when_fresh(self):
        import tempfile
        d=Path(tempfile.mkdtemp())
        res={'days':[{'date':'2026-11-11'}],'note':'Tableau.'}
        def relay(hours):
            (d/'relay.json').write_text(json.dumps({'sources':{'mm':{'status':'ok','fetched_at':(m.NOW-dt.timedelta(hours=hours)).isoformat(),'result':res}}}))
        with patch.object(m,'DATA',d):
            relay(2)
            r=m.collect_source('mm',lambda:1/0,{})
            self.assertEqual((r['status'],r['relay']),('ok',True))
            relay(8)
            self.assertEqual(m.collect_source('mm',lambda:1/0,{})['status'],'unavailable')

    def test_winter_rollover(self):
        self.assertEqual(m.season_year(dt.date(2027,2,1)),2026)
        self.assertEqual(m.season_year(dt.date(2027,11,1)),2027)

if __name__=='__main__':unittest.main()

import os,sys,unittest,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'robot-server'))
from app.speech.tts_fast import numbers_for_speech
from app.knowledge.teaching import TeachingStore
from app.core import access

class IPQFeatures(unittest.TestCase):
    def test_article_is_not_current(self):
        for text in ['A Arka ajuda a equipe.','a bateria está pronta','Vamos de 18 a 20 horas.','A interface responde a você.']:
            self.assertNotIn('ampères',numbers_for_speech(text))
    def test_current_with_and_without_space(self):
        for text in ['18A','18a','18 A','18 a','0,5A','2.5 A','-3A']:
            self.assertIn('ampères',numbers_for_speech(text),text)
        self.assertEqual(numbers_for_speech('18a'),'dezoito ampères')
        self.assertNotIn('ampères',numbers_for_speech('porta18a e A18'))
    def test_password_hash_and_roles(self):
        account=access.make_user('a-long-test-password','admin')
        with patch.object(access,'users',return_value={'tester':account}):
            self.assertIsNone(access.authenticate('tester','wrong','unit-ip'))
            self.assertEqual(access.authenticate('tester','a-long-test-password','unit-ip'),'admin')
            self.assertIsNone(access.authenticate('unknown','a-long-test-password','unit-ip'))
    def test_teaching_version_and_deactivation(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=TeachingStore(Path(tmp)/'teaching.sqlite3')
            id=store.save('Qual é o horário?','Às 9 horas.','admin',True)
            self.assertEqual(store.match('qual e o horario')['answer'],'Às 9 horas.')
            self.assertIsNone(store.match('Outra pergunta'))
            store.save('Qual é o horário?','Às 10 horas.','admin',False,id)
            self.assertIsNone(store.match('Qual é o horário?'))
            with store.connect() as conn:self.assertEqual(conn.execute('SELECT count(*) FROM revisions').fetchone()[0],1)

if __name__=='__main__':unittest.main()

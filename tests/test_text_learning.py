"""Regression coverage for shared teaching without sharing conversation history."""
import sys, tempfile, threading, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'robot-server'))
from qdrant_client import QdrantClient
from app.knowledge import text_learning as learning
from app.knowledge.teaching import TeachingStore
from app.sessions import Session
from app.core.web_conversation import respond

class TextLearningTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=TeachingStore(Path(self.tmp.name)/'lessons.db')
        self.client=QdrantClient(':memory:');self.addCleanup(self.client.close)
        for target,value in [('app.knowledge.text_learning.teachings',self.store),
                             ('app.knowledge.vector_store.client',self.client)]:
            p=patch(target,value);p.start();self.addCleanup(p.stop)
        p=patch('app.knowledge.embedder.embed_texts',return_value=[[1.,0.,0.]])
        p.start();self.addCleanup(p.stop)
    def test_explicit_commands_only(self):
        self.assertEqual(learning.teaching_fact('Arka, aprenda que o encontro é sexta.'),'o encontro é sexta.')
        self.assertEqual(learning.teaching_fact('Guarde que a sala é azul.'),'a sala é azul.')
        self.assertIsNone(learning.teaching_fact('A sala é azul?'))
    def test_published_edit_and_deactivation(self):
        identifier=learning.save('Horário do encontro','Sexta às dez.','admin')
        self.assertEqual(learning.retrieve('Quando ocorre o encontro?')[0]['answer'],'Sexta às dez.')
        learning.save('Horário do encontro','Sábado às dez.','admin',True,identifier)
        self.assertEqual(learning.retrieve('Quando ocorre o encontro?')[0]['answer'],'Sábado às dez.')
        learning.save('Horário do encontro','Sábado às dez.','admin',False,identifier)
        self.assertEqual(learning.retrieve('Quando ocorre o encontro?'),[])
    def test_embedding_failure_does_not_publish(self):
        with patch('app.knowledge.embedder.embed_texts',side_effect=RuntimeError('offline')):
            with self.assertRaises(RuntimeError):learning.save('Reunião','Toda sexta-feira.','admin')
        self.assertEqual(self.store.list(),[])
    def test_other_session_can_retrieve_but_not_teach(self):
        learning.save('Local de encontro','Sala Azul.','admin')
        events=[];session=Session('isolated',username='guest',role='viewer')
        with patch('app.core.web_conversation.prepare_voice_route',return_value={'route':'chat','question':'x'}), patch('app.knowledge.text_learning.save') as save:
            respond(session,'Arka, aprenda que o local é outro.',lambda kind,value:events.append((kind,value)),threading.Event())
        save.assert_not_called()
        self.assertIn('Somente administradores',events[-1][1]['text'])
        self.assertEqual(learning.retrieve('Onde é o encontro?')[0]['answer'],'Sala Azul.')
        self.assertEqual(len(session.history),2)

if __name__=='__main__':unittest.main()

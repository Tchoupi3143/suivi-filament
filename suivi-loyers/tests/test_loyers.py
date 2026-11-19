# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests de Suivi Loyers.   python3 -m unittest discover -s tests"""
import importlib
import os
import sys
import tempfile
import unittest

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(ICI), "src"))
sys.path.insert(0, ICI)
from faux_smtp import FauxSMTP   # noqa: E402

CSV = """Date;Libellé;Débit euros;Crédit euros;
02/10/2026;VIR SEPA RECU /DE M DUPONT JEAN /MOTIF LOYER;;850,00;
03/10/2026;PRLV ASSURANCE;12,40;;
08/10/2026;VIR DE MME MARTIN CLAIRE;;600,00;
15/10/2026;VIR DE MME MARTIN CLAIRE COMPLEMENT;;520,00;
04/11/2026;VIREMENT CAF;;1 120,00;
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["SUIVI_LOYERS_DOSSIER"] = self.tmp.name
        os.environ["SUIVI_LOYERS_AUJOURDHUI"] = "2026-11-19"
        os.environ.pop("SUIVI_LOYERS_SMTP_MDP", None)
        import loyers
        self.L = importlib.reload(loyers)
        self.smtp = None

    def tearDown(self):
        if self.smtp:
            self.smtp.arreter()
        self.tmp.cleanup()

    def donnees(self, smtp=False):
        d = self.L.vierge()
        d["bailleur"].update(nom="SCI Les Lilas", signataire="Arthur Martin", adresse="1 rue A\n33000 Bordeaux",
                             ville="Bordeaux", email="moi@example.com")
        d["baux"] = [
            {"id": 1, "locataire": "Jean Dupont", "email": "jean@example.com", "logement": "Appt 1\n8 cours X",
             "jour_echeance": 5, "debut": "2026-10", "fin": None, "motifs": ["DUPONT"],
             "montants": [{"depuis": "2026-10", "loyer": 78000, "charges": 7000}]},
            {"id": 2, "locataire": "Claire Martin", "email": "claire@example.com", "logement": "Appt 2",
             "jour_echeance": 5, "debut": "2026-10", "fin": None, "motifs": [],
             "montants": [{"depuis": "2026-10", "loyer": 100000, "charges": 12000}]},
        ]
        if smtp:
            self.smtp = FauxSMTP()
            d["smtp"].update(hote="127.0.0.1", port=self.smtp.port, securite="aucune", expediteur="loyers@example.com")
        return d


class Releves(Base):
    def test_montants(self):
        c = self.L.releves.centimes
        self.assertEqual(c("1 234,56"), 123456)
        self.assertEqual(c("-1.234,56 €"), -123456)
        self.assertEqual(c("1,234.56"), 123456)
        self.assertEqual(c("+850"), 85000)
        self.assertEqual(c("850.5"), 85050)

    def test_csv_debit_credit(self):
        ops = self.L.releves.lire(CSV.encode("cp1252"), "r.csv")
        self.assertEqual(len(ops), 5)
        self.assertEqual(ops[0], {"date": "2026-10-02", "montant": 85000,
                                  "libelle": "VIR SEPA RECU /DE M DUPONT JEAN /MOTIF LOYER", "ref": None})
        self.assertEqual(ops[1]["montant"], -1240)

    def test_csv_colonne_montant_et_preambule(self):
        texte = ('"Compte";"123"\n"Solde";"1000"\n\n'
                 '"Date opération","Date valeur","Libellé","Montant"\n'
                 '"2026-11-02","2026-11-02","VIR DUPONT","850,00"\n"2026-11-03","2026-11-03","CB","-20,00"\n')
        texte = texte.replace('","', '";"').replace('"Compte";"123"', '"Compte";"123"')
        ops = self.L.releves.lire(texte.encode(), "r.csv")
        self.assertEqual([(o["date"], o["montant"]) for o in ops], [("2026-11-02", 85000), ("2026-11-03", -2000)])

    def test_ofx(self):
        ofx = ("OFXHEADER:100\n<OFX><BANKTRANLIST><STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20261102120000"
               "<TRNAMT>850.00<FITID>A1<NAME>VIR DUPONT<MEMO>LOYER</STMTTRN></BANKTRANLIST></OFX>")
        ops = self.L.releves.lire(ofx.encode(), "r.ofx")
        self.assertEqual(ops, [{"date": "2026-11-02", "montant": 85000, "libelle": "VIR DUPONT LOYER", "ref": "A1"}])

    def test_camt053(self):
        xml = """<?xml version="1.0"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"><BkToCstmrStmt><Stmt>
<Ntry><Amt Ccy="EUR">850.00</Amt><CdtDbtInd>CRDT</CdtDbtInd><BookgDt><Dt>2026-11-02</Dt></BookgDt>
<AcctSvcrRef>X1</AcctSvcrRef><NtryDtls><TxDtls><RltdPties><Dbtr><Nm>JEAN DUPONT</Nm></Dbtr></RltdPties>
<RmtInf><Ustrd>LOYER NOVEMBRE</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>
<Ntry><Amt Ccy="EUR">12.40</Amt><CdtDbtInd>DBIT</CdtDbtInd><BookgDt><Dt>2026-11-03</Dt></BookgDt></Ntry>
</Stmt></BkToCstmrStmt></Document>"""
        ops = self.L.releves.lire(xml.encode(), "r.xml")
        self.assertEqual(ops[0]["montant"], 85000)
        self.assertIn("DUPONT", ops[0]["libelle"])
        self.assertEqual(ops[1]["montant"], -1240)


class Rapprochement(Base):
    def test_import_reconnaissance_et_doublons(self):
        d = self.donnees()
        self.assertEqual(self.L.importer(d, CSV.encode(), "a.csv"), (5, 0))
        self.assertEqual(self.L.importer(d, CSV.encode(), "a.csv"), (0, 5))
        self.L.rapprocher(d)
        par_lib = {o["libelle"]: o for o in d["operations"]}
        self.assertEqual(par_lib["VIR SEPA RECU /DE M DUPONT JEAN /MOTIF LOYER"]["bail"], 1)
        self.assertEqual(par_lib["VIR DE MME MARTIN CLAIRE"]["bail"], 2)   # nom du locataire par défaut
        caf = par_lib["VIREMENT CAF"]
        self.assertNotIn("bail", caf)                                       # jamais d'attribution au seul montant
        self.assertEqual(caf["suggestion"], 2)
        self.assertNotIn("bail", par_lib["PRLV ASSURANCE"])

    def test_doublon_entre_deux_formats(self):
        d = self.donnees()
        self.L.importer(d, CSV.encode(), "a.csv")
        ofx = ("<OFX><STMTTRN><DTPOSTED>20261002<TRNAMT>850.00<FITID>Z<NAME>VIR M DUPONT</STMTTRN></OFX>")
        self.L.importer(d, ofx.encode(), "b.ofx")
        self.L.rapprocher(d)
        e = self.L.situation(d, d["baux"][0])[0]
        self.assertEqual(e["2026-10"]["paye"], 85000)
        self.assertEqual(e["2026-11"]["paye"], 0)                           # pas compté deux fois

    def test_paiement_partiel_puis_complet_et_avance(self):
        d = self.donnees()
        self.L.importer(d, CSV.encode(), "a.csv")
        self.L.rapprocher(d)
        martin = d["baux"][1]
        e = self.L.situation(d, martin)[0]
        self.assertEqual(e["2026-10"]["statut"], "payé")
        self.assertEqual(e["2026-10"]["date_paiement"], "2026-10-15")      # date du paiement qui solde le mois
        self.assertEqual(e["2026-11"]["statut"], "en retard")
        self.L.affecter(d, next(o["id"] for o in d["operations"] if o["libelle"] == "VIREMENT CAF"), 2)
        self.L.ajouter_paiement_manuel(d, 2, "20/11/2026", 50000, "chèque")
        e = self.L.situation(d, martin)[0]
        self.assertEqual(e["2026-11"]["statut"], "payé")
        self.assertEqual(e["2026-12"]["paye"], 50000)
        self.assertEqual(e["2026-12"]["statut"], "futur")

    def test_revision_de_loyer(self):
        d = self.donnees()
        d["baux"][0]["montants"].append({"depuis": "2026-11", "loyer": 80000, "charges": 7000})
        e = self.L.situation(d, d["baux"][0])[0]
        self.assertEqual(e["2026-10"]["du"], 85000)
        self.assertEqual(e["2026-11"]["du"], 87000)

    def test_retard_selon_echeance(self):
        os.environ["SUIVI_LOYERS_AUJOURDHUI"] = "2026-11-08"
        d = self.donnees()
        self.assertEqual(self.L.situation(d, d["baux"][0])[0]["2026-11"]["statut"], "attendu")
        os.environ["SUIVI_LOYERS_AUJOURDHUI"] = "2026-11-11"
        self.assertEqual(self.L.situation(d, d["baux"][0])[0]["2026-11"]["statut"], "en retard")


class Quittances(Base):
    def test_scan_complet_envoi_et_pas_de_renvoi(self):
        d = self.donnees(smtp=True)
        self.L.sauver(d)
        os.makedirs(self.L.BOITE, exist_ok=True)
        with open(os.path.join(self.L.BOITE, "releve.csv"), "w", encoding="utf-8") as f:
            f.write(CSV)
        r = self.L.scanner()
        self.assertEqual(sorted(r["envoyees"]), ["Claire Martin 2026-10", "Jean Dupont 2026-10"])
        self.assertEqual(os.listdir(self.L.BOITE), [])                      # relevé rangé
        self.assertEqual(len(os.listdir(self.L.RANGES)), 1)
        self.assertEqual(len(self.smtp.messages), 2)
        m = next(x for x in self.smtp.messages if x["To"] == "jean@example.com")
        self.assertIn("octobre 2026", m["Subject"])
        piece = next(m.iter_attachments())
        self.assertEqual(piece.get_filename(), "Quittance-2026-10.pdf")
        self.assertTrue(piece.get_content().startswith(b"%PDF-1.4"))
        self.assertEqual(m.destinataires, ["jean@example.com", "moi@example.com"])   # copie cachée au bailleur
        self.assertIsNone(m["Bcc"])
        # second passage : rien de neuf, rien de renvoyé
        r = self.L.scanner()
        self.assertEqual(r["envoyees"], [])
        self.assertEqual(len(self.smtp.messages), 2)

    def test_echec_envoi_reessaye(self):
        d = self.donnees()
        d["smtp"].update(hote="127.0.0.1", port=1, securite="aucune", expediteur="x@example.com")
        self.L.importer(d, CSV.encode(), "a.csv")
        self.L.rapprocher(d)
        cr = self.L.emettre(d)
        self.assertEqual(len(cr["erreurs"]), 2)
        q = self.L.trouver_quittance(d, 1, "2026-10")
        self.assertIsNone(q["envoyee_le"])
        self.assertTrue(q["erreur"])
        self.smtp = FauxSMTP()
        d["smtp"]["port"] = self.smtp.port
        self.assertEqual(len(self.L.emettre(d)["envoyees"]), 2)

    def test_pas_d_envoi_auto_des_vieux_mois(self):
        d = self.donnees(smtp=True)
        os.environ["SUIVI_LOYERS_AUJOURDHUI"] = "2027-02-10"
        self.L.importer(d, CSV.encode(), "a.csv")
        self.L.rapprocher(d)
        cr = self.L.emettre(d)
        self.assertTrue(cr["generees"])
        self.assertEqual(cr["envoyees"], [])

    def test_pdf_et_montant_en_lettres(self):
        qt = self.L.qt
        self.assertEqual(qt.montant_en_lettres(112000), "mille-cent-vingt euros")
        self.assertEqual(qt.montant_en_lettres(85050), "huit-cent-cinquante euros et cinquante centimes")
        self.assertEqual(qt.en_lettres(80), "quatre-vingts")
        self.assertEqual(qt.en_lettres(71), "soixante-et-onze")
        self.assertEqual(qt.en_lettres(2000), "deux-mille")
        bail = {"locataire": "Zoé (L'Hôte)", "logement": "Appt \\ 2"}
        pdf = qt.generer({"nom": "Moi", "ville": "Lyon"}, bail, "2026-02", 50000, 5000, 20000, "2026-02-03", "N1")
        self.assertTrue(pdf.startswith(b"%PDF") and pdf.rstrip().endswith(b"%%EOF"))
        self.assertIn(b"RE\xc7U DE PAIEMENT PARTIEL", pdf)                  # paiement partiel = reçu, en cp1252
        self.assertIn(b"Zo\xe9 \\(L'H\xf4te\\)", pdf)


if __name__ == "__main__":
    unittest.main()

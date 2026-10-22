import os
import cv2
import time
import threading
import numpy as np
import insightface

PASTA = "cadastrados"
LIMIAR = 0.60
PASTA_COMPARTILHADA = "/tmp/t800_comunicacao"
os.makedirs(PASTA_COMPARTILHADA, exist_ok=True)

print("A carregar modelo InsightFace...")
app = insightface.app.FaceAnalysis(name="buffalo_s", providers=["CPUExecutionProvider"])
app.prepare(ctx_id=-1, det_size=(320, 320))

banco = []
if os.path.exists(PASTA):
    for arq in os.listdir(PASTA):
        if arq.lower().endswith((".jpg", ".jpeg", ".png")):
            img = cv2.imread(os.path.join(PASTA, arq))
            fs = app.get(img)
            if fs:
                banco.append((os.path.splitext(arq)[0], fs[0].embedding))
print(f"Base carregada com {len(banco)} faces.")

rostos_atuais = []
rostos_suavizados = []
lock = threading.Lock()
ia_trabalhando = False
ultimo_anuncio = {}


def processar_ia(frame_para_ia):
    global ia_trabalhando, rostos_atuais
    faces = app.get(frame_para_ia)
    novos_rostos = []

    for face in faces:
        emb = face.embedding
        melhor = "Desconhecido"
        score = -1

        for nome, e in banco:
            sim = float(np.dot(emb, e) / (np.linalg.norm(emb) * np.linalg.norm(e)))
            if sim > score:
                score = sim
                melhor = nome

        if score < LIMIAR:
            melhor = "Desconhecido"

        bbox = face.bbox.astype(int)

        # Memória Espacial
        if melhor == "Desconhecido":
            cx_novo = (bbox[0] + bbox[2]) / 2
            cy_novo = (bbox[1] + bbox[3]) / 2
            with lock:
                referencia = list(rostos_atuais)
            for antigo_box, antigo_nome, antigo_score in referencia:
                if antigo_nome != "Desconhecido":
                    cx_antigo = (antigo_box[0] + antigo_box[2]) / 2
                    cy_antigo = (antigo_box[1] + antigo_box[3]) / 2
                    distancia = np.sqrt((cx_novo - cx_antigo) ** 2 + (cy_novo - cy_antigo) ** 2)
                    largura = antigo_box[2] - antigo_box[0]
                    if distancia < largura:
                        melhor = antigo_nome
                        score = antigo_score
                        break

        novos_rostos.append((bbox, melhor, score))

    with lock:
        rostos_atuais = novos_rostos
    ia_trabalhando = False


print("Gateway de Visão Ativo (Lendo direto da pasta partilhada)...")
frame_id = 0

while True:
    caminho_img = os.path.join(PASTA_COMPARTILHADA, "frame.jpg")
    if not os.path.exists(caminho_img):
        time.sleep(0.01)
        continue

    try:
        frame = cv2.imread(caminho_img)
        if frame is None:
            continue
    except:
        continue

    frame_id += 1

    # Dispara a IA a cada 3 frames
    if frame_id % 3 == 0 and not ia_trabalhando:
        ia_trabalhando = True
        threading.Thread(target=processar_ia, args=(frame.copy(),), daemon=True).start()

    # Suavização da caixa (Lerp)
    with lock:
        if not rostos_suavizados and rostos_atuais:
            rostos_suavizados = list(rostos_atuais)
        elif rostos_atuais:
            temp_suv = []
            for i, novo in enumerate(rostos_atuais):
                if i < len(rostos_suavizados):
                    antigo_box, _, _ = rostos_suavizados[i]
                    novo_box, novo_nome, novo_score = novo
                    box_suave = antigo_box * 0.5 + novo_box * 0.5
                    temp_suv.append((box_suave.astype(int), novo_nome, novo_score))
                else:
                    temp_suv.append(novo)
            rostos_suavizados = temp_suv
        else:
            rostos_suavizados = []

    # Desenhar no ecrã e enviar comando de voz se reconhecer
    for bbox, nome, score in rostos_suavizados:
        x1, y1, x2, y2 = bbox
        cor = (0, 255, 0) if nome != "Desconhecido" else (0, 0, 255)
        cv2.rectangle(frame, (x1, y1), (x2, y2), cor, 2)
        cv2.putText(frame, f"{nome} {score:.2f}", (x1, y1 - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.6, cor, 2)

        if nome != "Desconhecido":
            agora = time.time()
            if nome not in ultimo_anuncio or agora - ultimo_anuncio[nome] > 5.0:
                ultimo_anuncio[nome] = agora
                try:
                    with open(os.path.join(PASTA_COMPARTILHADA, "fala.txt"), "w") as f:
                        f.write(f"Acesso autorizado. Olá, {nome}!")
                except:
                    pass

    cv2.imshow("Visao T800 - Gateway Local", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cv2.destroyAllWindows()
import discord
from discord.ext import commands
import sqlite3

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# ===== BANCO DE DADOS =====
def conectar():
    conn = sqlite3.connect('economia.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            user_id INTEGER PRIMARY KEY,
            saldo INTEGER DEFAULT 0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS loja (
            nome TEXT,
            descricao TEXT,
            preco INTEGER,
            categoria TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS inventario (
            user_id INTEGER,
            item_nome TEXT,
            tipo TEXT,
            slot TEXT DEFAULT '',
            equipado INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    return conn

# ===== COMANDOS ECONOMIA =====
@bot.command()
async def saldo(ctx):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT saldo FROM usuarios WHERE user_id = ?", (ctx.author.id,))
    result = cursor.fetchone()
    saldo = result[0] if result else 0
    await ctx.send(f"{ctx.author.mention}, seu saldo é {saldo} moedas.")
    conn.close()

@bot.command()
@commands.has_permissions(administrator=True)
async def adddinheiro(ctx, membro: discord.Member, valor: int):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO usuarios (user_id, saldo) VALUES (?, 0)", (membro.id,))
    cursor.execute("UPDATE usuarios SET saldo = saldo + ? WHERE user_id = ?", (valor, membro.id))
    conn.commit()
    await ctx.send(f"{membro.mention} recebeu {valor} moedas!")
    conn.close()

@bot.command()
@commands.has_permissions(administrator=True)
async def resetdinheiro(ctx, membro: discord.Member):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("UPDATE usuarios SET saldo = 0 WHERE user_id = ?", (membro.id,))
    conn.commit()
    conn.close()
    await ctx.send(f"🧨 O saldo de {membro.mention} foi resetado para 0 moedas.")



# ===== SISTEMA DE LOJA =====
class ItemView(discord.ui.View):
    def __init__(self, nome_item, preco, user_id):
        super().__init__(timeout=None)
        self.nome_item = nome_item
        self.preco = preco
        self.user_id = user_id

    @discord.ui.button(label="🛒 Comprar", style=discord.ButtonStyle.green)
    async def comprar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Essa loja não é sua.", ephemeral=True)
            return

        conn = conectar()
        cursor = conn.cursor()

        cursor.execute("SELECT saldo FROM usuarios WHERE user_id = ?", (interaction.user.id,))
        result = cursor.fetchone()
        saldo = result[0] if result else 0

        if saldo < self.preco:
            await interaction.response.send_message("❌ Você não tem moedas suficientes.", ephemeral=True)
        else:
            cursor.execute("UPDATE usuarios SET saldo = saldo - ? WHERE user_id = ?", (self.preco, interaction.user.id))
            tipo = 'consumivel' if 'poção' in self.nome_item.lower() else 'equipavel'
            slot = 'arma' if 'espada' in self.nome_item.lower() else 'armadura' if 'armadura' in self.nome_item.lower() else 'acessorio'
            cursor.execute("INSERT INTO inventario (user_id, item_nome, tipo, slot) VALUES (?, ?, ?, ?)",
                           (interaction.user.id, self.nome_item, tipo, slot if tipo == 'equipavel' else ''))
            conn.commit()
            await interaction.response.send_message(f"✅ {interaction.user.mention} comprou **{self.nome_item}** por {self.preco} moedas!")
            await interaction.channel.send(f"🎉 {interaction.user.mention} comprou **{self.nome_item}**!")
        conn.close()

class CategoriaView(discord.ui.View):
    def __init__(self, categorias, itens_por_categoria, user_id):
        super().__init__(timeout=None)
        self.categorias = categorias
        self.itens_por_categoria = itens_por_categoria
        self.user_id = user_id
        self.categoria_atual = categorias[0]
        self.update_buttons()

    def update_buttons(self):
        self.clear_items()
        for cat in self.categorias:
            style = discord.ButtonStyle.primary if cat == self.categoria_atual else discord.ButtonStyle.secondary
            self.add_item(CategoriaButton(cat, style, self))

    async def atualizar_mensagem(self, interaction):
        await interaction.message.delete()
        for nome, descricao, preco in self.itens_por_categoria[self.categoria_atual]:
            embed = discord.Embed(
                title=f"{nome}",
                description=f"{descricao}\n\n💰 **Preço:** {preco} moedas",
                color=discord.Color.orange()
            )
            await interaction.channel.send(embed=embed, view=ItemView(nome, preco, self.user_id))

class CategoriaButton(discord.ui.Button):
    def __init__(self, categoria, style, view):
        super().__init__(label=categoria, style=style)
        self.categoria = categoria
        self.parent_view = view

    async def callback(self, interaction: discord.Interaction):
        self.parent_view.categoria_atual = self.categoria
        self.parent_view.update_buttons()
        await self.parent_view.atualizar_mensagem(interaction)

@bot.command()
async def shop(ctx):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT nome, descricao, preco, categoria FROM loja")
    dados = cursor.fetchall()
    conn.close()

    if not dados:
        await ctx.send("A loja está vazia.")
        return

    itens_por_categoria = {}
    for nome, descricao, preco, categoria in dados:
        if categoria not in itens_por_categoria:
            itens_por_categoria[categoria] = []
        itens_por_categoria[categoria].append((nome, descricao, preco))

    categorias = list(itens_por_categoria.keys())
    view = CategoriaView(categorias, itens_por_categoria, ctx.author.id)
    await ctx.send(f"🛒 {ctx.author.mention}, selecione uma categoria:", view=view)

# ===== INVENTARIO =====
@bot.command()
async def inventario(ctx):
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("SELECT item_nome FROM inventario WHERE user_id = ? AND tipo = 'consumivel'", (ctx.author.id,))
    consumiveis = [row[0] for row in cursor.fetchall()]

    cursor.execute("SELECT item_nome, slot, equipado FROM inventario WHERE user_id = ? AND tipo = 'equipavel'", (ctx.author.id,))
    equipaveis_raw = cursor.fetchall()

    equipados = []
    mochila = []
    for item, slot, equipado in equipaveis_raw:
        if equipado:
            equipados.append(f"**{slot.capitalize()}**: {item}")
        else:
            mochila.append(f"{item} ({slot})")

    conn.close()

    embed = discord.Embed(title=f"🎒 Inventário de {ctx.author.display_name}", color=discord.Color.dark_teal())
    if consumiveis:
        embed.add_field(name="🍎 Consumíveis", value="\n".join(f"• {item}" for item in consumiveis), inline=False)
    if mochila:
        embed.add_field(name="🛡️ Equipáveis (Não equipados)", value="\n".join(f"• {item}" for item in mochila), inline=False)
    if equipados:
        embed.add_field(name="🧤 Itens Equipados", value="\n".join(equipados), inline=False)

    if not (consumiveis or mochila or equipados):
        embed.description = "Você não possui nenhum item."

    await ctx.send(embed=embed)

@bot.command()
async def usar(ctx, *, nome_item):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT rowid FROM inventario WHERE user_id = ? AND item_nome = ? AND tipo = 'consumivel'", (ctx.author.id, nome_item))
    item = cursor.fetchone()

    if item:
        cursor.execute("DELETE FROM inventario WHERE rowid = ?", (item[0],))
        conn.commit()
        await ctx.send(f"🍷 {ctx.author.mention} usou **{nome_item}**!")
    else:
        await ctx.send("❌ Você não possui esse item consumível.")
    conn.close()

### CÓDIGO ATUALIZADO COM DESEQUIPAR AUTOMÁTICO AO ULTRAPASSAR LIMITE

@bot.command()
async def equipar(ctx, *, nome_item):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT slot FROM inventario WHERE user_id = ? AND item_nome = ? AND tipo = 'equipavel'", (ctx.author.id, nome_item))
    item = cursor.fetchone()

    if not item:
        await ctx.send("❌ Item não encontrado ou não é equipável.")
        conn.close()
        return

    slot = item[0]

    # Limites definidos por tipo de slot
    limites = {
        "arma": 1,
        "capacete": 1,
        "peitoral": 1,
        "calça": 1,
        "bota": 1,
        "bracelete": 2,
        "anel": 1,
        "pulseira": 1,
        "colar": 1,
        "oculos": 1,
        "capa": 1
    }

    limite = limites.get(slot, 1)

    # Conta quantos itens já estão equipados nesse slot
    cursor.execute("SELECT item_nome FROM inventario WHERE user_id = ? AND slot = ? AND equipado = 1", (ctx.author.id, slot))
    equipados = cursor.fetchall()

    if len(equipados) >= limite:
        for equipado in equipados:
            cursor.execute("UPDATE inventario SET equipado = 0 WHERE user_id = ? AND item_nome = ?", (ctx.author.id, equipado[0]))

    cursor.execute("UPDATE inventario SET equipado = 1 WHERE user_id = ? AND item_nome = ?", (ctx.author.id, nome_item))
    conn.commit()
    conn.close()
    await ctx.send(f"🛡️ {ctx.author.mention} equipou **{nome_item}** no slot **{slot}**!")


### NOVO COMANDO: DESEQUIPAR ITEM

@bot.command()
async def desequipar(ctx, *, nome_item):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT equipado FROM inventario WHERE user_id = ? AND item_nome = ? AND tipo = 'equipavel'", (ctx.author.id, nome_item))
    item = cursor.fetchone()

    if not item:
        await ctx.send("❌ Item não encontrado no seu inventário.")
    elif item[0] == 0:
        await ctx.send("❗ Esse item já está desequipado.")
    else:
        cursor.execute("UPDATE inventario SET equipado = 0 WHERE user_id = ? AND item_nome = ?", (ctx.author.id, nome_item))
        conn.commit()
        await ctx.send(f"❌ {ctx.author.mention} desequipou **{nome_item}**.")
    conn.close()


### NOVO COMANDO: VER ITENS EQUIPADOS

@bot.command()
async def equipados(ctx):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT item_nome, slot FROM inventario WHERE user_id = ? AND equipado = 1", (ctx.author.id,))
    itens = cursor.fetchall()
    conn.close()

    if not itens:
        await ctx.send(f"{ctx.author.mention}, você não tem nenhum item equipado.")
    else:
        texto = "\n".join([f"**{slot.capitalize()}**: {nome}" for nome, slot in itens])
        embed = discord.Embed(title=f"🧤 Itens Equipados de {ctx.author.display_name}", description=texto, color=discord.Color.blue())
        await ctx.send(embed=embed)


@bot.event
async def on_ready():
    print(f'🤖 Bot conectado como {bot.user}')



bot.command()
@commands.has_permissions(administrator=True)
async def removeritem(ctx, *, nome_item):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM loja WHERE nome = ?", (nome_item,))
    conn.commit()
    conn.close()
    await ctx.send(f"❌ Item **{nome_item}** removido da loja.")

@bot.command()
@commands.has_permissions(administrator=True)
async def removercategoria(ctx, *, categoria):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM loja WHERE categoria = ?", (categoria,))
    conn.commit()
    conn.close()
    await ctx.send(f"🗑️ Categoria **{categoria}** removida da loja.")

@bot.command()
async def troca(ctx, membro: discord.Member, valor: int):
    if valor <= 0:
        await ctx.send("❌ Valor inválido para troca.")
        return

    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT saldo FROM usuarios WHERE user_id = ?", (ctx.author.id,))
    result = cursor.fetchone()
    saldo = result[0] if result else 0

    if saldo < valor:
        await ctx.send("❌ Você não tem moedas suficientes para fazer a troca.")
    else:
        cursor.execute("UPDATE usuarios SET saldo = saldo - ? WHERE user_id = ?", (valor, ctx.author.id))
        cursor.execute("INSERT OR IGNORE INTO usuarios (user_id, saldo) VALUES (?, 0)", (membro.id,))
        cursor.execute("UPDATE usuarios SET saldo = saldo + ? WHERE user_id = ?", (valor, membro.id))
        conn.commit()
        await ctx.send(f"🔁 {ctx.author.mention} transferiu {valor} moedas para {membro.mention}!")
    conn.close()


# ===== ATUALIZAÇÃO ADDITEM COM TIPO =====
@bot.command()
@commands.has_permissions(administrator=True)
async def additem(ctx, nome_entre_aspas: str, *args):
    try:
        preco = int(args[-3])
        categoria = args[-2]
        tipo = args[-1].lower()
        descricao = " ".join(args[:-3])

        if tipo not in ['equipavel', 'consumivel']:
            await ctx.send("❌ Tipo inválido. Use 'equipavel' ou 'consumivel'.")
            return

        conn = conectar()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO loja (nome, descricao, preco, categoria) VALUES (?, ?, ?, ?)",
                       (nome_entre_aspas, descricao, preco, categoria))
        conn.commit()
        await ctx.send(f"✅ Item **{nome_entre_aspas}** adicionado à loja por {preco} moedas na categoria **{categoria}**. Tipo: {tipo}")
        conn.close()
    except (IndexError, ValueError):
        await ctx.send("❌ Formato inválido. Use:\n`!additem \"Nome do Item\" descrição... <preço> <categoria> <tipo>`")


@bot.command()
@commands.has_permissions(administrator=True)
async def daritem(ctx, membro: discord.Member, nome_entre_aspas: str, *args):
    try:
        preco = int(args[-3])  # O preço pode ser ignorado mas está aqui para manter consistência de estrutura
        categoria = args[-2]   # Categoria pode ser usada como referência futura ou organização
        tipo = args[-1].lower()
        descricao = " ".join(args[:-3])

        if tipo not in ['equipavel', 'consumivel']:
            await ctx.send("❌ Tipo inválido. Use 'equipavel' ou 'consumivel'.")
            return

        slot = ''
        if tipo == 'equipavel':
            palavras = ['arma', 'capacete', 'peitoral', 'calça', 'bota', 'bracelete', 'anel', 'pulseira', 'colar', 'oculos', 'capa']
            for p in palavras:
                if p in nome_entre_aspas.lower() or p in descricao.lower():
                    slot = p
                    break
            if slot == '':
                await ctx.send("❌ Slot não identificado para item equipável. Inclua o nome do slot no nome ou descrição.")
                return

        conn = conectar()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO inventario (user_id, item_nome, tipo, slot) VALUES (?, ?, ?, ?)",
                       (membro.id, nome_entre_aspas, tipo, slot))
        conn.commit()
        conn.close()
        await ctx.send(f"🎁 {ctx.author.mention} deu o item **{nome_entre_aspas}** para {membro.mention}!")

    except (IndexError, ValueError):
        await ctx.send("❌ Formato inválido. Use:\n`!daritem @usuário \"Nome do Item\" descrição... <preço> <categoria> <tipo>`")



@bot.command()
@commands.has_permissions(administrator=True)
async def removeritem(ctx, *, nome_item):
    conn = conectar()
    cursor = conn.cursor()

    # Verifica se o item existe
    cursor.execute("SELECT * FROM loja WHERE nome = ?", (nome_item,))
    item = cursor.fetchone()

    if not item:
        await ctx.send(f"❌ O item **{nome_item}** não foi encontrado na loja.")
    else:
        cursor.execute("DELETE FROM loja WHERE nome = ?", (nome_item,))
        conn.commit()
        await ctx.send(f"🗑️ O item **{nome_item}** foi removido da loja com sucesso.")

    conn.close()




import os
bot.run(os.getenv('DISCORD_TOKEN'))

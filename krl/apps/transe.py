import typer
from pathlib import Path
import torch
from torch.utils.data import DataLoader

from config import DatasetConf, TrainConf
from models.transe import TransE, TransEHyperParam
from dataset import create_mapping, KRLDataset
from trainer import TransETrainer
from negative_sampler import RandomNegativeSampler
import storage


def get_device() -> torch.device:
    return torch.device('cuda') if torch.cuda.is_available() else torch.device('cpu')

app = typer.Typer()

@app.command(name='train')
def train_transe(
        dataset_name: str = typer.Option(...),
        base_dir: Path = typer.Option(...),
        batch_size: int = typer.Option(...),
        valid_batch_size: int = typer.Option(...),
        valid_freq: int = typer.Option(...),
        lr: float = typer.Option(...),
        epoch_size: int = typer.Option(...),
        embed_dim: int = typer.Option(...),
        norm: int = typer.Option(...),
        margin: float = typer.Option(...),
        ckpt_path: Path = typer.Option(...),
        metric_result_path: Path = typer.Option(...)
    ):
    if not base_dir.exists():
        print("base_dir doesn't exists.")
        raise typer.Exit()
    dataset_conf = DatasetConf(
        dataset_name=dataset_name,
        base_dir=base_dir.absolute().as_posix()
    )
    train_conf = TrainConf(
        checkpoint_path=ckpt_path.absolute().as_posix(),
        metric_result_path=metric_result_path.absolute().as_posix()
    )
    hyper_params = TransEHyperParam(
        batch_size=batch_size,
        valid_batch_size=valid_batch_size,
        learning_rate=lr,
        epoch_size=epoch_size,
        embed_dim=embed_dim,
        norm=norm,
        margin=margin,
        valid_freq=valid_freq
    )
    # create mapping
    entity2id, rel2id = create_mapping(dataset_conf)
    device = get_device()
    ent_num = len(entity2id)
    rel_num = len(rel2id)
    
    # create dataset and dataloader
    train_dataset = KRLDataset(dataset_conf, 'train', entity2id, rel2id)
    train_dataloder = DataLoader(train_dataset, hyper_params.batch_size)
    valid_dataset = KRLDataset(dataset_conf, 'valid', entity2id, rel2id)
    valid_dataloder = DataLoader(valid_dataset, hyper_params.valid_batch_size)
    
    # create negative-sampler
    neg_sampler = RandomNegativeSampler(train_dataset, device)

    # create model
    model = TransE(ent_num, rel_num, device, norm, embed_dim, margin)
    model = model.to(device)
    
    # create optimizer
    optimizer = torch.optim.Adam(model.parameters(), lr=hyper_params.learning_rate)
    
    # create trainer
    trainer = TransETrainer(
        model=model,
        train_conf=train_conf,
        params=hyper_params,
        dataset_conf=dataset_conf,
        entity2id=entity2id,
        rel2id=rel2id,
        device=device,
        train_dataloder=train_dataloder,
        valid_dataloder=valid_dataloder,
        train_neg_sampler=neg_sampler,
        valid_neg_sampler=neg_sampler,
        optimzer=optimizer
    )
    
    # training process
    trainer.run_training()
    
    # Testing the best checkpoint on test dataset
    ckpt = storage.load_checkpoint(train_conf)
    model.load_state_dict(ckpt.model_state_dict)
    model = model.to(device)
    test_dataset = KRLDataset(dataset_conf, 'test', entity2id, rel2id)
    test_dataloder = DataLoader(test_dataset, hyper_params.valid_batch_size)
    hits_at_1, hits_at_3, hits_at_10, mrr = trainer.run_inference(test_dataloder, ent_num)
    
    # write results
    with open(train_conf.metric_result_path, 'w') as f:
        f.write(f'dataset: {dataset_conf.dataset_name}\n')
        f.write(f'Hits@1: {hits_at_1}\n')
        f.write(f'Hits@3: {hits_at_3}\n')
        f.write(f'Hits@10: {hits_at_10}\n')
        f.write(f'MRR: {mrr}\n')
